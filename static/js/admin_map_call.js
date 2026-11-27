(function () {
  const el = document.getElementById("watch-map");
  if (!el) return;
  if (typeof L === "undefined") return;

  const callLat = parseFloat(el.dataset.callLat);
  const callLng = parseFloat(el.dataset.callLng);
  const callReason = el.dataset.callReason || "";
  const callPatient = el.dataset.callPatient || "";
  const callAddress = el.dataset.callAddress || "";

  const ownerLat = el.dataset.ownerLat !== "" ? parseFloat(el.dataset.ownerLat) : null;
  const ownerLng = el.dataset.ownerLng !== "" ? parseFloat(el.dataset.ownerLng) : null;
  const ownerName = el.dataset.ownerName || "";
  const callId = el.dataset.callId;

  const routeStatusEl = document.getElementById("watch-route-status");

  if (isNaN(callLat) || isNaN(callLng)) return;

  const map = L.map(el, { zoomControl: true, attributionControl: true })
    .setView([callLat, callLng], 13);

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "© OpenStreetMap contributors",
  }).addTo(map);

  setTimeout(() => map.invalidateSize(), 150);

  const callMarker = L.marker([callLat, callLng]).addTo(map);
  callMarker.bindPopup(
    `<strong>${callReason}</strong><br>${callPatient}<br>${callAddress}`
  );

  if (ownerLat === null || ownerLng === null) {
    if (routeStatusEl) routeStatusEl.textContent = "Машина не назначена";
    return;
  }

  const ownerIcon = L.divIcon({
    className: "ambulance-marker",
    html: `<img src="/static/img/icons/ambulance.svg" alt="Ambulance">`,
    iconSize: [32, 32],
    iconAnchor: [16, 16],
  });
  const ownerMarker = L.marker([ownerLat, ownerLng], { icon: ownerIcon }).addTo(map);
  ownerMarker.bindPopup(`<strong>${ownerName}</strong><br>На вызове #${callId}`);

  const bounds = L.latLngBounds([[callLat, callLng], [ownerLat, ownerLng]]);
  map.fitBounds(bounds, { padding: [40, 40] });

  async function buildRoute() {
    if (routeStatusEl) routeStatusEl.textContent = "Строится…";
    const url =
      `https://router.project-osrm.org/route/v1/driving/` +
      `${ownerLng},${ownerLat};${callLng},${callLat}` +
      `?overview=full&geometries=geojson`;

    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error("osrm");
      const json = await res.json();
      if (!json.routes || !json.routes.length) throw new Error("no route");

      const route = json.routes[0];
      const coords = route.geometry.coordinates.map(([lng, lat]) => [lat, lng]);

      const line = L.polyline(coords, {
        color: "#e53935",
        weight: 5,
        opacity: 0.85,
      }).addTo(map);

      map.fitBounds(line.getBounds(), { padding: [40, 40] });

      const km = (route.distance / 1000).toFixed(1);
      const min = Math.round(route.duration / 60);
      if (routeStatusEl) routeStatusEl.textContent = `${km} км · ~${min} мин`;
    } catch (e) {
      L.polyline([[ownerLat, ownerLng], [callLat, callLng]], {
        color: "#e53935",
        weight: 4,
        opacity: 0.6,
        dashArray: "6 8",
      }).addTo(map);
      if (routeStatusEl) routeStatusEl.textContent = "Прямой путь (нет связи)";
    }
  }

  buildRoute();
})();