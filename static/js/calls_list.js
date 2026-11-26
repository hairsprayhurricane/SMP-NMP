(function () {
  const FIELD_KEY = "search_field";
  const LAYERS_KEY = "map_layers_v1";

  const toggle      = document.getElementById("field-toggle");
  const menu        = document.getElementById("field-menu");
  const label       = document.getElementById("field-label");
  const input       = document.getElementById("field-input");
  const search      = document.getElementById("calls-search");
  const results     = document.getElementById("results");
  const refreshBtn  = document.getElementById("refresh-btn");
  const maskView    = document.getElementById("phone-mask-view");
  const inputWrap   = document.getElementById("search-input-wrap");
  const sortBtn     = document.getElementById("sort-distance-btn");
  const viewInput   = document.getElementById("view-input");
  const mapToggle   = document.getElementById("map-toggle-btn");
  const listToggle  = document.getElementById("list-toggle-btn");
  const contentArea = document.getElementById("content-area");
  const mapEl       = document.getElementById("map");
  const mapShell    = document.getElementById("map-shell");

  const layerBtnAmbulances = document.getElementById("layer-btn-ambulances");
  const layerBtnCalls      = document.getElementById("layer-btn-calls");
  const layerBtnActive     = document.getElementById("layer-btn-active");

  if (!toggle || !menu || !input || !results) return;

  const labels = {
    name:    "Поиск по ФИО",
    address: "Поиск по адресу",
    phone:   "Поиск по номеру телефона",
  };

  let currentView = viewInput ? viewInput.value : "all";
  let mapMode = false;
  let listMode = contentArea ? contentArea.style.display !== "none" : true;

  const activeCallId = mapEl ? (mapEl.dataset.activeCallId || "") : "";
  const userRole     = mapEl ? (mapEl.dataset.role || "") : "";
  const focusCallId  = mapEl ? (parseInt(mapEl.dataset.focusCall, 10) || null) : null;
  const isAdmin      = userRole === "admin" || userRole === "superadmin";

  const PHONE_TEMPLATE = "XXX XXX-XX-XX";
  const MAX_DIGITS = 10;
  let phoneDigits = "";

  function renderMaskHTML() {
    let html = "+7 ";
    let di = 0;
    for (let i = 0; i < PHONE_TEMPLATE.length; i++) {
      const ch = PHONE_TEMPLATE[i];
      if (ch === "X") {
        if (di < phoneDigits.length) html += phoneDigits[di];
        else html += '<span class="phone-x">X</span>';
        di++;
      } else html += ch;
    }
    return html;
  }

  function updateMaskView() {
    if (maskView) maskView.innerHTML = renderMaskHTML();
  }

  function setPhoneMode(on) {
    if (on) {
      phoneDigits = "";
      search.value = "";
      search.placeholder = "";
      search.inputMode = "numeric";
      search.setAttribute("autocomplete", "off");
      if (maskView) maskView.hidden = false;
      if (inputWrap) inputWrap.classList.add("phone-mode");
      updateMaskView();
    } else {
      phoneDigits = "";
      search.value = "";
      search.placeholder = "Поиск по базе вызовов";
      search.removeAttribute("inputMode");
      search.removeAttribute("autocomplete");
      if (maskView) {
        maskView.hidden = true;
        maskView.innerHTML = "";
      }
      if (inputWrap) inputWrap.classList.remove("phone-mode");
    }
  }

  const saved = localStorage.getItem(FIELD_KEY);
  if (saved && labels[saved]) {
    const url = new URL(window.location.href);
    if (!url.searchParams.get("field") && input.value !== saved) {
      input.value = saved;
      label.textContent = labels[saved];
    }
  }

  if (input.value === "phone") {
    const initialQ = (search.value || "").replace(/\D/g, "");
    setPhoneMode(true);
    if (initialQ) {
      let d = initialQ;
      if (d.startsWith("7")) d = d.slice(1);
      phoneDigits = d.slice(0, MAX_DIGITS);
      search.value = phoneDigits;
      updateMaskView();
    }
  }

  toggle.addEventListener("click", (e) => {
    e.stopPropagation();
    menu.hidden = !menu.hidden;
  });

  menu.querySelectorAll("button[data-field]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const field = btn.dataset.field;
      const wasPhone = input.value === "phone";
      input.value = field;
      label.textContent = labels[field];
      localStorage.setItem(FIELD_KEY, field);
      menu.hidden = true;

      if (field === "phone") setPhoneMode(true);
      else if (wasPhone) setPhoneMode(false);

      if (mapMode) loadMapData();
      else runSearch(1);
    });
  });

  document.addEventListener("click", (e) => {
    if (!menu.hidden && !menu.contains(e.target) && e.target !== toggle) {
      menu.hidden = true;
    }
  });

  search.addEventListener("beforeinput", (e) => {
    if (input.value !== "phone") return;
    if (e.inputType === "insertText" && !/^\d$/.test(e.data || "")) {
      e.preventDefault();
      return;
    }
    if (e.inputType === "insertFromPaste") {
      const pasted = (e.dataTransfer && e.dataTransfer.getData("text")) || "";
      const digits = pasted.replace(/\D/g, "");
      if (!digits) { e.preventDefault(); return; }
      e.preventDefault();
      for (const d of digits) {
        if (phoneDigits.length >= MAX_DIGITS) break;
        phoneDigits += d;
      }
      search.value = phoneDigits;
      updateMaskView();
      if (mapMode) loadMapData();
      else runSearch(1);
      return;
    }
    if (e.inputType === "insertText" && phoneDigits.length >= MAX_DIGITS) {
      e.preventDefault();
    }
  });

  search.addEventListener("input", () => {
    if (input.value !== "phone") {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        if (mapMode) loadMapData();
        else runSearch(1);
      }, 300);
      return;
    }
    const raw = search.value.replace(/\D/g, "");
    let digits = raw;
    if (digits.startsWith("7")) digits = digits.slice(1);
    phoneDigits = digits.slice(0, MAX_DIGITS);
    if (search.value !== phoneDigits) search.value = phoneDigits;
    updateMaskView();
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      if (mapMode) loadMapData();
      else runSearch(1);
    }, 300);
  });

  search.addEventListener("keydown", (e) => {
    if (input.value !== "phone") return;
    if (e.key === "Backspace" || e.key === "Delete") {
      e.preventDefault();
      if (phoneDigits.length > 0) {
        phoneDigits = phoneDigits.slice(0, -1);
        search.value = phoneDigits;
        updateMaskView();
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
          if (mapMode) loadMapData();
          else runSearch(1);
        }, 300);
      }
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      clearTimeout(debounceTimer);
      if (mapMode) loadMapData();
      else runSearch(1);
    }
  });

  search.addEventListener("keydown", (e) => {
    if (input.value === "phone") return;
    if (e.key === "Enter") {
      e.preventDefault();
      clearTimeout(debounceTimer);
      if (mapMode) loadMapData();
      else runSearch(1);
    }
  });

  if (sortBtn) {
    sortBtn.addEventListener("click", () => {
      currentView = (currentView === "nearest") ? "all" : "nearest";
      sortBtn.classList.toggle("btn-active", currentView === "nearest");
      if (viewInput) viewInput.value = currentView;

      if (mapMode) loadMapData();
      else runSearch(1);
    });
  }

  let debounceTimer = null;
  let abortController = null;

  async function runSearch(page = 1) {
    const field = input.value;
    let q;
    if (field === "phone") q = phoneDigits;
    else q = search.value.trim();

    if (abortController) abortController.abort();
    abortController = new AbortController();

    const params = new URLSearchParams({ q, field, page, view: currentView });

    try {
      const res = await fetch("/fe/search?" + params.toString(), {
        signal: abortController.signal,
      });
      if (!res.ok) return;
      const html = await res.text();
      results.innerHTML = html;
      bindPagination();
    } catch (err) {
      if (err.name !== "AbortError") console.error(err);
    }
  }

  function bindPagination() {
    const pag = document.getElementById("pagination");
    if (!pag) return;
    pag.querySelectorAll(".pagination-link").forEach((a) => {
      a.addEventListener("click", (e) => {
        e.preventDefault();
        const page = parseInt(a.dataset.page, 10) || 1;
        runSearch(page);
      });
    });
  }

  if (refreshBtn) {
    refreshBtn.addEventListener("click", (e) => {
      e.preventDefault();
      localStorage.removeItem(FIELD_KEY);
      window.location.href = "/fe/";
    });
  }

  let map = null;
  let callMarkers = [];
  let ambulanceMarkers = {};
  let routeLines = [];
  let ambulanceMarkerSelf = null;
  let refreshTimer = null;

  const layerState = { ambulances: true, calls: true, active: false };
  let lastMapData = { calls: [], doctors: [] };

  function loadLayerState() {
    if (!isAdmin) {
      layerState.ambulances = true;
      layerState.calls = true;
      layerState.active = false;
      return;
    }
    try {
      const raw = localStorage.getItem(LAYERS_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (typeof parsed.ambulances === "boolean") layerState.ambulances = parsed.ambulances;
      if (typeof parsed.calls === "boolean") layerState.calls = parsed.calls;
      if (typeof parsed.active === "boolean") layerState.active = parsed.active;
    } catch (e) {}
  }

  function saveLayerState() {
    if (!isAdmin) return;
    try {
      localStorage.setItem(LAYERS_KEY, JSON.stringify(layerState));
    } catch (e) {}
  }

  function syncLayerButtons() {
    if (layerBtnAmbulances) {
      layerBtnAmbulances.classList.toggle("is-active", layerState.ambulances);
      layerBtnAmbulances.setAttribute("aria-pressed", layerState.ambulances ? "true" : "false");
    }
    if (layerBtnCalls) {
      layerBtnCalls.classList.toggle("is-active", layerState.calls);
      layerBtnCalls.setAttribute("aria-pressed", layerState.calls ? "true" : "false");
    }
    if (layerBtnActive) {
      layerBtnActive.classList.toggle("is-active", layerState.active);
      layerBtnActive.setAttribute("aria-pressed", layerState.active ? "true" : "false");
    }
  }

  function bindLayerButtons() {
    if (layerBtnAmbulances) {
      layerBtnAmbulances.addEventListener("click", () => {
        layerState.ambulances = !layerState.ambulances;
        saveLayerState();
        syncLayerButtons();
        renderMapData();
      });
    }
    if (layerBtnCalls) {
      layerBtnCalls.addEventListener("click", () => {
        layerState.calls = !layerState.calls;
        saveLayerState();
        syncLayerButtons();
        renderMapData();
      });
    }
    if (layerBtnActive) {
      layerBtnActive.addEventListener("click", () => {
        layerState.active = !layerState.active;
        saveLayerState();
        syncLayerButtons();
        renderMapData();
      });
    }
  }

  loadLayerState();
  syncLayerButtons();
  bindLayerButtons();

  function setMapMode(on) {
    mapMode = on;
    if (contentArea) contentArea.style.display = on ? "none" : (listMode ? "" : "none");
    if (mapShell) mapShell.style.display = on ? "" : "none";

    if (mapToggle) {
      mapToggle.classList.toggle("btn-active", on);
      const state = mapToggle.querySelector(".map-toggle-state");
      if (state) state.textContent = on ? "[on]" : "[off]";
    }

    if (on) {
      if (currentView === "nearest") {
        currentView = "all";
        if (sortBtn) sortBtn.classList.remove("btn-active");
        if (viewInput) viewInput.value = "all";
      }
      initMap();
      startAutoRefresh();
    } else {
      stopAutoRefresh();
    }
  }

  if (mapToggle) {
    mapToggle.addEventListener("click", () => setMapMode(!mapMode));
  }

  if (listToggle) {
    listToggle.addEventListener("click", () => {
      listMode = !listMode;
      const st = listToggle.querySelector(".list-toggle-state");
      if (st) st.textContent = listMode ? "[on]" : "[off]";
      listToggle.classList.toggle("btn-active", listMode);
      if (contentArea && !mapMode) {
        contentArea.style.display = listMode ? "" : "none";
      }
    });
  }

  function initMap() {
    if (!mapEl || typeof L === "undefined") return;

    if (!map) {
      map = L.map(mapEl).setView([43.585, 39.723], 12);
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: "© OpenStreetMap contributors",
      }).addTo(map);
      startGeolocation();
    }

    setTimeout(() => map.invalidateSize(), 100);
    loadMapData();
  }

  async function loadMapData() {
    try {
      const res = await fetch("/fe/api/map_data?view=" + encodeURIComponent(currentView));
      if (!res.ok) return;
      const data = await res.json();
      renderMapData(data);
    } catch (e) {
      console.error("Не удалось загрузить данные карты", e);
    }
  }

  function renderMapData(data) {
    if (data) lastMapData = data;

    callMarkers.forEach((m) => map.removeLayer(m));
    callMarkers = [];

    const showCalls  = layerState.calls || layerState.active;
    const onlyActive = layerState.active && !layerState.calls;
    let visibleCalls = 0;

    if (showCalls) {
      lastMapData.calls.forEach((p) => {
        const isActive = !!p.active_owner;
        if (onlyActive && !isActive) return;

        visibleCalls++;
        const marker = L.marker([p.lat, p.lng]).addTo(map);

        marker.on("mousedown", (e) => L.DomEvent.stopPropagation(e));
        marker.on("dblclick", (e) => L.DomEvent.stopPropagation(e));

        const distText = (p.distance_km != null)
          ? `<br>≈ ${p.distance_km} км от скорой`
          : "";
        const priorityHtml = p.priority_label
          ? `<br><span class="priority-mark priority-mark-${p.priority}">${p.priority_label}</span>`
          : "";
        const reasonHtml = p.reason
          ? `<strong>${p.reason}</strong><br>`
          : "";

        let infoHtml = `
          <div class="map-popup">
            ${reasonHtml}
            ${p.patient_name}<br>
            ${p.address}${distText}${priorityHtml}
        `;

        if (userRole === 'doctor') {
          infoHtml += `<div class="map-popup-hint">Двойной клик — взять вызов</div>`;
        }
        if (p.active_owner) {
          infoHtml += `<div class="map-popup-hint">Взят: ${p.active_owner}</div>`;
        }
        infoHtml += `</div>`;

        const confirmHtml = `
          <div class="map-popup map-popup-confirm">
            <strong>Взять вызов?</strong><br>
            ${reasonHtml}
            ${p.patient_name}<br>
            ${p.address}
            <div class="map-popup-actions">
              <button type="button" class="map-popup-btn map-popup-yes"
                      data-call-id="${p.id}">Да</button>
              <button type="button" class="map-popup-btn map-popup-no">Нет</button>
            </div>
          </div>
        `;

        marker.bindPopup(infoHtml);

        if (userRole === 'doctor') {
          let clickTimer = null;
          marker.on("click", (e) => {
            L.DomEvent.stopPropagation(e);
            if (clickTimer) {
              clearTimeout(clickTimer);
              clickTimer = null;
              marker.setPopupContent(confirmHtml);
              marker.openPopup();
            } else {
              clickTimer = setTimeout(() => { clickTimer = null; }, 300);
            }
          });
        }

        marker.on("popupopen", (e) => {
          const popupEl = e.popup.getElement();
          if (!popupEl) return;

          const yesBtn = popupEl.querySelector(".map-popup-yes");
          const noBtn = popupEl.querySelector(".map-popup-no");

          if (yesBtn && !yesBtn.disabled && userRole === 'doctor') {
            yesBtn.addEventListener("click", () => {
              const callId = yesBtn.dataset.callId;
              const form = document.createElement("form");
              form.method = "POST";
              form.action = `/fe/call/${callId}/accept`;

              const csrfInput = document.querySelector('input[name="_csrf"]');
              if (csrfInput) {
                const hiddenInput = document.createElement("input");
                hiddenInput.type = "hidden";
                hiddenInput.name = "_csrf";
                hiddenInput.value = csrfInput.value;
                form.appendChild(hiddenInput);
              }

              document.body.appendChild(form);
              form.submit();
            });
          }

          if (noBtn && !noBtn.disabled && userRole === 'doctor') {
            noBtn.addEventListener("click", () => map.closePopup());
          }
        });

        callMarkers.push(marker);
      });
    }

    Object.values(ambulanceMarkers).forEach((m) => map.removeLayer(m));
    ambulanceMarkers = {};
    routeLines.forEach((l) => map.removeLayer(l));
    routeLines = [];

    const showAmbulances = isAdmin && (layerState.ambulances || layerState.active);
    const onlyActiveAmbulances = layerState.active && !layerState.ambulances;
    let visibleAmbulances = 0;
    let activeAmbulances = 0;

    if (showAmbulances) {
      lastMapData.doctors.forEach((d) => {
        if (onlyActiveAmbulances && !d.active_call_id) return;

        visibleAmbulances++;
        if (d.active_call_id) activeAmbulances++;

        const icon = L.divIcon({
          className: "ambulance-marker",
          html: "🚑",
          iconSize: [32, 32],
          iconAnchor: [16, 16],
        });
        const m = L.marker([d.lat, d.lng], { icon }).addTo(map);
        let popup = `<strong>${d.name}</strong>`;
        if (d.active_call_id) {
          popup += `<br>На вызове #${d.active_call_id}`;
        } else {
          popup += `<br>Свободна`;
        }
        m.bindPopup(popup);
        ambulanceMarkers[d.login] = m;

        if (d.active_call_id && layerState.active) {
          const targetCall = lastMapData.calls.find(c => c.id === d.active_call_id);
          if (targetCall) {
            drawRoute(d.lat, d.lng, targetCall.lat, targetCall.lng);
          }
        }
      });
    }

    const metricCalls = document.getElementById("metric-calls");
    const metricAmbulances = document.getElementById("metric-ambulances");
    const metricActive = document.getElementById("metric-active");
    if (metricCalls) metricCalls.textContent = String(visibleCalls);
    if (metricAmbulances) metricAmbulances.textContent = String(visibleAmbulances);
    if (metricActive) metricActive.textContent = String(activeAmbulances);

    if (focusCallId && map) {
      const target = lastMapData.calls.find(c => c.id === focusCallId);
      if (target) {
        map.setView([target.lat, target.lng], 15);
      }
    }
  }

  async function drawRoute(fromLat, fromLng, toLat, toLng) {
    const url = `https://router.project-osrm.org/route/v1/driving/${fromLng},${fromLat};${toLng},${toLat}?overview=full&geometries=geojson`;
    try {
      const res = await fetch(url);
      if (!res.ok) return;
      const json = await res.json();
      if (!json.routes || !json.routes.length) return;
      const coords = json.routes[0].geometry.coordinates.map(([lng, lat]) => [lat, lng]);
      const line = L.polyline(coords, {
        color: "#e53935",
        weight: 4,
        opacity: 0.8,
        dashArray: "8 6",
      }).addTo(map);
      routeLines.push(line);
    } catch (e) {
      const line = L.polyline([[fromLat, fromLng], [toLat, toLng]], {
        color: "#e53935", weight: 3, opacity: 0.6, dashArray: "6 8",
      }).addTo(map);
      routeLines.push(line);
    }
  }

  function startGeolocation() {
    if (userRole !== "doctor") return;
    if (!navigator.geolocation) return;

    navigator.geolocation.watchPosition(
      (pos) => {
        const lat = pos.coords.latitude;
        const lng = pos.coords.longitude;

        if (!ambulanceMarkerSelf) {
          const ambulanceIcon = L.divIcon({
            className: "ambulance-marker",
            html: "🚑",
            iconSize: [32, 32],
            iconAnchor: [16, 16],
          });
          ambulanceMarkerSelf = L.marker([lat, lng], { icon: ambulanceIcon }).addTo(map);
          ambulanceMarkerSelf.bindPopup("Ваше местоположение");
        } else {
          ambulanceMarkerSelf.setLatLng([lat, lng]);
        }
      },
      (err) => console.warn("Геолокация:", err.message),
      { enableHighAccuracy: true, maximumAge: 5000, timeout: 10000 }
    );
  }

  function startAutoRefresh() {
    stopAutoRefresh();
    refreshTimer = setInterval(() => {
      if (mapMode) loadMapData();
    }, 8000);
  }

  function stopAutoRefresh() {
    if (refreshTimer) {
      clearInterval(refreshTimer);
      refreshTimer = null;
    }
  }

  bindPagination();

  if (mapShell) {
    mapShell.style.display = "none";
  }

  if (mapEl && mapEl.dataset.initMap === "1" && !mapMode) {
    setMapMode(true);
  }
})();