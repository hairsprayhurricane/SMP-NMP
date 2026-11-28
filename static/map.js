// Карта вызова и определение положения планшета.
// Любая проблема (нет Leaflet, нет связи, нет разрешения на геолокацию) не должна ломать страницу:
// остаются адрес вызова, кнопки внешних карт и все остальные функции.
// Положение планшета остаётся в браузере: на сервер не отправляется и нигде не сохраняется.
(function () {
  "use strict";

  var mapEl = document.getElementById("call-map");
  var note = document.getElementById("map-note");
  var map = null;

  function showNote() {
    if (note) note.hidden = false;
  }

  // ---------- карта ----------
  if (mapEl) {
    if (typeof L === "undefined") {  // библиотека не загрузилась (нет интернета и нет локальной копии)
      mapEl.hidden = true;
      showNote();
    } else {
      try {
        var lat = parseFloat(mapEl.getAttribute("data-lat"));
        var lon = parseFloat(mapEl.getAttribute("data-lon"));
        var zoom = parseInt(mapEl.getAttribute("data-zoom"), 10) || 16;
        if (isNaN(lat) || isNaN(lon)) throw new Error("bad coordinates");

        // На планшете один палец прокручивает страницу, а не двигает карту; масштаб: щипок или кнопки +/-.
        map = L.map(mapEl, {
          scrollWheelZoom: false,
          dragging: !L.Browser.mobile,
          maxBounds: [[42.7, 38.2], [44.5, 41.5]],
          maxBoundsViscosity: 1.0,
          minZoom: 10
        });
        map.setView([lat, lon], zoom);

        var layer = L.tileLayer(
          mapEl.getAttribute("data-tiles") || "/tiles/{z}/{x}/{y}.png",
          {
            maxZoom: 19,
            attribution: mapEl.getAttribute("data-attribution") || "© 2ГИС"
          }
        );
        if (map.attributionControl) map.attributionControl.setPrefix(false);
        var loaded = 0;
        var failed = 0;
        layer.on("tileload", function () { loaded += 1; });
        layer.on("tileerror", function () {
          failed += 1;
          if (loaded === 0 && failed >= 3) showNote();  // фон карты недоступен, метка остаётся
        });
        layer.addTo(map);

        L.circleMarker([lat, lon], {
          radius: 12, color: "#842029", weight: 3, fillColor: "#dc3545", fillOpacity: 0.9
        }).addTo(map);
      } catch (e) {
        map = null;
        mapEl.hidden = true;
        showNote();
      }
    }
  }

  // ---------- положение планшета ----------
  var btn = document.getElementById("geo-btn");
  if (!btn) return;
  var statusEl = document.getElementById("geo-status");
  var routeEl = document.getElementById("route-from-here");
  var callLat = parseFloat(btn.getAttribute("data-lat"));
  var callLon = parseFloat(btn.getAttribute("data-lon"));
  var userLayers = [];

  function setStatus(text) {
    statusEl.textContent = text;
    statusEl.hidden = false;
  }

  function distanceM(lat1, lon1, lat2, lon2) {  // по прямой, формула гаверсинусов
    var rad = Math.PI / 180;
    var dLat = (lat2 - lat1) * rad;
    var dLon = (lon2 - lon1) * rad;
    var a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
            Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
    return 6371000 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  }

  function formatDistance(m) {
    if (m < 1000) return (Math.round(m / 10) * 10) + " м";
    return (m / 1000).toFixed(1).replace(".", ",") + " км";
  }

  function formatAccuracy(m) {
    return m < 1000 ? "±" + Math.round(m) + " м" : "±" + (m / 1000).toFixed(1).replace(".", ",") + " км";
  }

  function drawOnMap(uLat, uLon, accuracy) {
    if (!map) return;
    try {
      userLayers.forEach(function (layer) { map.removeLayer(layer); });
      userLayers = [];
      userLayers.push(L.circle([uLat, uLon], { radius: accuracy, color: "#0d6efd", weight: 1, fillOpacity: 0.1 }).addTo(map));
      userLayers.push(L.circleMarker([uLat, uLon], {
        radius: 9, color: "#084298", weight: 3, fillColor: "#0d6efd", fillOpacity: 0.9
      }).addTo(map));
      map.fitBounds(L.latLngBounds([[callLat, callLon], [uLat, uLon]]), { padding: [40, 40], maxZoom: 17 });
    } catch (e) { /* карта не обязательна: расстояние и маршрут уже показаны */ }
  }

  function onSuccess(pos) {
    var uLat = pos.coords.latitude;
    var uLon = pos.coords.longitude;
    var accuracy = pos.coords.accuracy || 0;
    var text = "До места вызова по прямой: " + formatDistance(distanceM(uLat, uLon, callLat, callLon)) +
               ". Точность определения: " + formatAccuracy(accuracy) + ".";
    if (accuracy > 1000) text += " Положение определено грубо, на него нельзя полностью полагаться.";
    setStatus(text);

    routeEl.href = "https://yandex.ru/maps/?rtext=" + uLat.toFixed(6) + "," + uLon.toFixed(6) + "~" +
                   callLat.toFixed(6) + "," + callLon.toFixed(6) + "&rtt=auto";
    routeEl.hidden = false;
    drawOnMap(uLat, uLon, accuracy);
    finish();
  }

  function onError(err) {
    var messages = {
      1: "Доступ к геолокации запрещён. Разрешите её для этого сайта в настройках браузера и нажмите кнопку ещё раз.",
      2: "Не удалось определить положение: нет сигнала GPS или сети. Выйдите на открытое место и повторите.",
      3: "Определение положения заняло слишком много времени. Повторите попытку."
    };
    setStatus(messages[err && err.code] || "Не удалось определить положение планшета.");
    finish();
  }

  function finish() {
    btn.disabled = false;
    btn.textContent = "Обновить моё местоположение";
  }

  function locate() {
    if (window.isSecureContext === false) {  // браузер блокирует геолокацию на страницах без HTTPS
      setStatus("Геолокация работает только при защищённом соединении (HTTPS). Обратитесь к администратору.");
      return;
    }
    if (!navigator.geolocation) {
      setStatus("Этот браузер не поддерживает определение положения.");
      return;
    }
    btn.disabled = true;
    btn.textContent = "Определяю…";
    setStatus("Определяю положение планшета…");
    try {
      navigator.geolocation.getCurrentPosition(onSuccess, onError, {
        enableHighAccuracy: true, timeout: 20000, maximumAge: 30000
      });
    } catch (e) {
      onError(null);
    }
  }

  btn.addEventListener("click", locate);

  // Если разрешение уже выдано, положение определяется само, без нажатия.
  try {
    if (navigator.permissions && navigator.permissions.query && window.isSecureContext !== false) {
      navigator.permissions.query({ name: "geolocation" }).then(function (p) {
        if (p.state === "granted") locate();
      }, function () {});
    }
  } catch (e) { /* не критично */ }
})();
