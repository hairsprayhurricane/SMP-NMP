(function () {
  "use strict";

  window.mapOfflineReady = false;

  var statusEl = document.getElementById("map-offline-status");
  function setStatus(text, ready) {
    if (!statusEl) return;
    statusEl.textContent = text;
    if (ready) statusEl.classList.add("is-ready");
    else statusEl.classList.remove("is-ready");
  }

  if (!("serviceWorker" in navigator)) {
    setStatus("Офлайн-карта недоступна в этом браузере", false);
    return;
  }

  navigator.serviceWorker.addEventListener("message", function (event) {
    var msg = event.data || {};
    if (msg.type === "precache-progress") {
      setStatus("Кэш карты " + msg.done + "/" + msg.total, false);
    } else if (msg.type === "precache-done") {
      window.mapOfflineReady = !msg.error;
      setStatus(
        "Офлайн-карта готова (" + msg.count + " плиток)",
        window.mapOfflineReady
      );
      window.dispatchEvent(new CustomEvent("map-precache-done", { detail: msg }));
    }
  });

  navigator.serviceWorker.register("/sw.js", { scope: "/", updateViaCache: "none" })
    .then(function (registration) {
      function startPrecache() {
        var worker = registration.active || registration.waiting || registration.installing;
        if (worker) worker.postMessage({ type: "precache-map" });
      }
      if (registration.active) startPrecache();
      else navigator.serviceWorker.ready.then(startPrecache);
    })
    .catch(function () {
      setStatus("Карта: офлайн-режим не включён", false);
    });
})();
