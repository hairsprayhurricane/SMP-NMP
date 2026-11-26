const TILE_CACHE = "local-tiles-v1";
const STATIC_CACHE = "local-static-v1";

self.addEventListener("install", () => {
  // Активируем новый SW сразу, не дожидаясь закрытия всех вкладок
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      // Удаляем старые версии кэшей
      const keys = await caches.keys();
      await Promise.all(
        keys
          .filter((k) => k !== TILE_CACHE && k !== STATIC_CACHE)
          .map((k) => caches.delete(k))
      );
      await self.clients.claim();
    })()
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // 1) Тайлы с нашего Flask-прокси: cache-first
  if (url.pathname.startsWith("/tiles/")) {
    event.respondWith(cacheFirst(event.request, TILE_CACHE));
    return;
  }

  // 2) Leaflet (локальные файлы из static/vendor/leaflet/)
  if (url.pathname.includes("/vendor/leaflet/")) {
    event.respondWith(cacheFirst(event.request, STATIC_CACHE));
    return;
  }

  // 3) Наши CSS/JS — cache-first с обновлением в фоне
  if (
    url.origin === self.location.origin &&
    (url.pathname.startsWith("/static/css/") ||
     url.pathname.startsWith("/static/js/"))
  ) {
    event.respondWith(staleWhileRevalidate(event.request, STATIC_CACHE));
    return;
  }
});

async function cacheFirst(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  if (cached) return cached;
  try {
    const res = await fetch(request);
    if (res.ok) cache.put(request, res.clone());
    return res;
  } catch {
    return new Response("", { status: 404 });
  }
}

async function staleWhileRevalidate(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  const fetchPromise = fetch(request)
    .then((res) => {
      if (res.ok) cache.put(request, res.clone());
      return res;
    })
    .catch(() => cached);
  return cached || fetchPromise;
}