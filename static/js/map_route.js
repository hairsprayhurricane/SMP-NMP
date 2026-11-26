(function () {
  const dataEl = document.getElementById("route-data");
  const mapEl = document.getElementById("route-map");
  const statusEl = document.getElementById("route-status");
  const recalcBtn = document.getElementById("recalc-btn");
  const retryGeoBtn = document.getElementById("retry-geo-btn");
  const manualBtn = document.getElementById("manual-locate-btn");

  if (!mapEl) {
    console.error("route: #route-map не найден");
    return;
  }

  if (typeof L === "undefined") {
    if (statusEl) statusEl.textContent =
      "Ошибка: Leaflet не загружен. Проверьте подключение к интернету.";
    console.error("route: L is undefined — Leaflet не подключён");
    return;
  }

  let data = null;
  try {
    data = JSON.parse(dataEl ? dataEl.textContent : "{}");
  } catch (e) {
    console.error("route: не удалось разобрать route-data", e);
  }
  if (!data || data.to_lat == null || data.to_lng == null) {
    if (statusEl) statusEl.textContent = "Ошибка: координаты вызова не заданы.";
    return;
  }

  const toLatLng = [data.to_lat, data.to_lng];

  const map = L.map(mapEl, { zoomControl: true }).setView(toLatLng, 13);

  // OSM-тайлы напрямую с CDN
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "© OpenStreetMap contributors",
  }).addTo(map);

  setTimeout(() => map.invalidateSize(), 200);

  L.marker(toLatLng).addTo(map).bindPopup(`<strong>${data.address || ""}</strong>`);

  let fromMarker = null;
  let routeLine = null;
  let routeAbort = null;
  let manualMode = false;
  let autoTimer = null;
  let watchId = null;

  function setStatus(text) { if (statusEl) statusEl.textContent = text; }

  function setFromPoint(lat, lng, source) {
    if (!fromMarker) {
      fromMarker = L.marker([lat, lng], {
        icon: L.divIcon({
          className: "ambulance-marker",
          html: "🚑",
          iconSize: [32, 32],
          iconAnchor: [16, 16],
        }),
      }).addTo(map).bindPopup(source === "manual" ? "🚑 Вы указали здесь" : "🚑 Вы здесь");
    } else {
      fromMarker.setLatLng([lat, lng]);
    }
    buildRoute(lat, lng);
  }

  function drawDirectLine(fromLat, fromLng) {
    if (routeLine) map.removeLayer(routeLine);
    routeLine = L.polyline([[fromLat, fromLng], toLatLng], {
      color: "#dc3545", weight: 4, dashArray: "8 8",
    }).addTo(map);
  }

  async function buildRoute(fromLat, fromLng) {
    setStatus("Строим маршрут…");
    if (routeAbort) routeAbort.abort();
    routeAbort = new AbortController();
    const timeout = setTimeout(() => routeAbort.abort(), 6000);

    try {
      const url = `https://router.project-osrm.org/route/v1/driving/` +
                  `${fromLng},${fromLat};${data.to_lng},${data.to_lat}` +
                  `?overview=full&geometries=geojson`;
      const res = await fetch(url, { signal: routeAbort.signal });
      clearTimeout(timeout);
      if (!res.ok) throw new Error("osrm");
      const json = await res.json();
      if (!json.routes || !json.routes.length) throw new Error("no route");

      const route = json.routes[0];
      const coords = route.geometry.coordinates.map(([lng, lat]) => [lat, lng]);

      if (routeLine) map.removeLayer(routeLine);
      routeLine = L.polyline(coords, { color: "#198754", weight: 6 }).addTo(map);
      map.fitBounds(routeLine.getBounds(), { padding: [30, 30] });

      const distKm = (route.distance / 1000).toFixed(1);
      const durMin = Math.round(route.duration / 60);
      setStatus(`Маршрут: ${distKm} км, ~${durMin} мин`);
    } catch (e) {
      clearTimeout(timeout);
      if (e.name === "AbortError") return;
      setStatus("Нет интернета — показан прямой путь. При подключении маршрут перестроится.");
      drawDirectLine(fromLat, fromLng);
    }
  }

  function requestGeolocation() {
    if (!navigator.geolocation) { setStatus("Геолокация недоступна."); return; }
    setStatus("Запрашиваем доступ к геолокации…");

    navigator.geolocation.getCurrentPosition(
      (pos) => {
        manualMode = false;
        setFromPoint(pos.coords.latitude, pos.coords.longitude, "geo");
        if (watchId !== null) navigator.geolocation.clearWatch(watchId);
        watchId = navigator.geolocation.watchPosition(
          (p2) => { if (!manualMode) setFromPoint(p2.coords.latitude, p2.coords.longitude, "geo"); },
          () => {},
          { enableHighAccuracy: true, maximumAge: 5000, timeout: 10000 }
        );
      },
      (err) => {
        if (statusEl) statusEl.textContent =
          err.code === 1
            ? "Доступ к геолокации запрещён. Нажмите «🖐 Указать местоположение»."
            : "Не удалось получить геолокацию: " + err.message;
      },
      { enableHighAccuracy: true, maximumAge: 5000, timeout: 10000 }
    );
  }

  if (retryGeoBtn) retryGeoBtn.addEventListener("click", requestGeolocation);

  if (manualBtn) {
    manualBtn.addEventListener("click", () => {
      manualMode = true;
      setStatus("Кликните на карте, где вы находитесь.");
      map.getContainer().style.cursor = "crosshair";
      map.once("click", (e) => {
        map.getContainer().style.cursor = "";
        setFromPoint(e.latlng.lat, e.latlng.lng, "manual");
      });
    });
  }

  if (recalcBtn) {
    recalcBtn.addEventListener("click", () => {
      if (fromMarker) {
        const ll = fromMarker.getLatLng();
        buildRoute(ll.lat, ll.lng);
      } else {
        requestGeolocation();
      }
    });
  }

  requestGeolocation();

  autoTimer = setInterval(() => {
    if (fromMarker && !manualMode) {
      const ll = fromMarker.getLatLng();
      buildRoute(ll.lat, ll.lng);
    }
  }, 20000);

  window.addEventListener("beforeunload", () => {
    if (autoTimer) clearInterval(autoTimer);
    if (routeAbort) routeAbort.abort();
    if (watchId !== null) navigator.geolocation.clearWatch(watchId);
  });

  window.addEventListener("load", () => setTimeout(() => map.invalidateSize(), 300));
})();