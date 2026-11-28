/* Офлайн-кэш приложения и карты 2ГИС.
   Тайлы приходят с нашего /tiles/... (диск-кэш на сервере),
   а этот service worker хранит их ещё и в браузере. */
const VERSION = "smp-offline-v3";
const TILE_CACHE = VERSION + "-tiles";
const STATIC_CACHE = VERSION + "-static";
const DATA_CACHE = VERSION + "-data";

const CORE_ASSETS = [
  "/login",
  "/fe/",
  "/style.css",
  "/static/css/base.css",
  "/static/css/auth.css",
  "/static/img/earth.jpg",
  "/static/css/calls_list.css",
  "/static/css/map_route.css",
  "/static/css/admin_map_call.css",
  "/static/js/base.js",
  "/static/js/sw-register.js",
  "/static/js/calls_list.js",
  "/static/js/form.js",
  "/static/js/map.js",
  "/static/js/map_route.js",
  "/static/js/admin_map_call.js",
  "/static/vendor/bootstrap.min.css",
  "/static/vendor/bootstrap.bundle.min.js",
  "/static/vendor/leaflet/leaflet.css",
  "/static/vendor/leaflet/leaflet.js",
  "/static/vendor/leaflet/images/marker-icon.png",
  "/static/vendor/leaflet/images/marker-icon-2x.png",
  "/static/vendor/leaflet/images/marker-shadow.png",
  "/static/vendor/leaflet/images/layers.png",
  "/static/vendor/leaflet/images/layers-2x.png",
];

let mapPrecacheInFlight = null;

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(
    (async () => {
      const cache = await caches.open(STATIC_CACHE);
      await Promise.all(
        CORE_ASSETS.map(async (url) => {
          try {
            const res = await fetch(url, { cache: "reload" });
            if (res.ok) await cache.put(url, res.clone());
          } catch (e) {
            /* один_missing файл не должен ломать установку SW */
          }
        })
      );
    })()
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys
          .filter((k) => !k.startsWith(VERSION + "-"))
          .map((k) => caches.delete(k))
      );
      await self.clients.claim();
    })()
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname === "/sw.js") return;

  // Тайлы 2ГИС через локальный прокси: сначала кэш, потом сеть.
  if (url.pathname.startsWith("/tiles/")) {
    event.respondWith(cacheFirst(req, TILE_CACHE));
    return;
  }

  // Данные точек карты: сеть с обновлением кэша, при потере сети — последняя копия.
  if (url.pathname === "/fe/api/map_data") {
    event.respondWith(mapData(req));
    return;
  }

  if (req.mode === "navigate") {
    event.respondWith(navigation(req));
    return;
  }

  if (
    url.pathname.startsWith("/static/") ||
    url.pathname === "/style.css"
  ) {
    event.respondWith(staleWhileRevalidate(req, STATIC_CACHE));
  }
});

async function cacheFirst(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  if (cached) return cached;
  try {
    const res = await fetch(request);
    if (res.ok) await cache.put(request, res.clone());
    return res;
  } catch (e) {
    return new Response("", { status: 504, statusText: "offline" });
  }
}

async function staleWhileRevalidate(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  const network = fetch(request)
    .then((res) => {
      if (res.ok) cache.put(request, res.clone());
      return res;
    })
    .catch(() => cached);
  return cached || network;
}

async function mapData(request) {
  const cache = await caches.open(DATA_CACHE);
  try {
    const res = await fetch(request);
    if (res.ok) await cache.put(request, res.clone());
    return res;
  } catch (e) {
    const exact = await cache.match(request);
    if (exact) return exact;
    const keys = await cache.keys();
    const any = keys.find((k) => new URL(k.url).pathname === "/fe/api/map_data");
    if (any) {
      const fallback = await cache.match(any);
      if (fallback) return fallback;
    }
    return new Response(
      JSON.stringify({ calls: [], doctors: [], offline: true }),
      { headers: { "Content-Type": "application/json; charset=utf-8" } }
    );
  }
}

async function navigation(request) {
  try {
    return await fetch(request);
  } catch (e) {
    const cache = await caches.open(STATIC_CACHE);
    const url = new URL(request.url);
    const fallbackUrl = url.pathname.startsWith("/fe") ? "/fe/" : "/login";
    const page = (await cache.match(request)) || (await cache.match(fallbackUrl));
    if (page) return page;
    return new Response("Нет сети и нет сохранённой страницы", {
      status: 503,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  }
}

self.addEventListener("message", (event) => {
  const msg = event.data || {};
  if (msg.type !== "precache-map") return;
  if (mapPrecacheInFlight) return;
  mapPrecacheInFlight = precacheMap(event.source || null).finally(() => {
    mapPrecacheInFlight = null;
  });
  event.waitUntil(mapPrecacheInFlight);
});

async function precacheMap(source) {
  function post(payload) {
    if (source && typeof source.postMessage === "function") source.postMessage(payload);
  }

  try {
    const manifestRes = await fetch("/tiles/manifest.json", { cache: "no-store" });
    if (!manifestRes.ok) throw new Error("manifest " + manifestRes.status);
    const manifest = await manifestRes.json();

    const tileUrls = (manifest.tiles || []).map((u) =>
      u.startsWith("/tiles/") ? u : "/tiles/" + u
    );
    const dataUrls = [
      "/fe/api/map_data?view=all",
      "/fe/api/map_data?view=nearest",
    ];
    const all = tileUrls.map((u) => ({ url: u, cache: TILE_CACHE })).concat(
      dataUrls.map((u) => ({ url: u, cache: DATA_CACHE }))
    );

    const tileCache = await caches.open(TILE_CACHE);
    const dataCache = await caches.open(DATA_CACHE);
    let done = 0;
    let stored = 0;

    const CONCURRENCY = 16;
    for (let i = 0; i < all.length; i += CONCURRENCY) {
      const chunk = all.slice(i, i + CONCURRENCY);
      const results = await Promise.all(
        chunk.map(async (item) => {
          const cache = item.cache === TILE_CACHE ? tileCache : dataCache;
          if (await cache.match(item.url)) return true;
          try {
            const res = await fetch(item.url, { credentials: "same-origin" });
            if (!res.ok) return false;
            await cache.put(item.url, res.clone());
            return true;
          } catch (e) {
            return false;
          }
        })
      );
      stored += results.filter(Boolean).length;
      done += chunk.length;
      post({ type: "precache-progress", done: done, total: all.length });
    }

    post({ type: "precache-done", count: stored, total: all.length });
  } catch (e) {
    post({ type: "precache-done", count: 0, total: 0, error: String(e) });
  }
}
