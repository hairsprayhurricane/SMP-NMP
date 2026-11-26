(function () {
  function blockZoomHard() {
    function blockKey(e) {
      if (!e.ctrlKey && !e.metaKey) return;
      const k = (e.key || "").toLowerCase();
      const code = e.keyCode || e.which;
      const zoomKeys = [
        "+", "-", "=", "_", "add", "subtract", "0", "numpadadd", "numpadsubtract",
      ];
      if (
        zoomKeys.includes(k) ||
        code === 187 || code === 189 || code === 107 || code === 109 ||
        code === 48 || code === 96
      ) {
        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation();
        return false;
      }
    }

    function blockWheel(e) {
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation();
        return false;
      }
    }

    function blockGesture(e) {
      e.preventDefault();
      e.stopPropagation();
      return false;
    }

    document.addEventListener("keydown", blockKey, { capture: true, passive: false });
    window.addEventListener("keydown", blockKey, { capture: true, passive: false });
    window.addEventListener("wheel", blockWheel, { capture: true, passive: false });
    document.addEventListener("wheel", blockWheel, { capture: true, passive: false });

    ["gesturestart", "gesturechange", "gestureend"].forEach((ev) => {
      document.addEventListener(ev, blockGesture, { passive: false });
      window.addEventListener(ev, blockGesture, { passive: false });
    });

    document.addEventListener("touchmove", (e) => {
      if (e.touches && e.touches.length > 1) {
        e.preventDefault();
      }
    }, { passive: false });

    let lastTouchEnd = 0;
    document.addEventListener("touchend", (e) => {
      const now = Date.now();
      if (now - lastTouchEnd <= 300) {
        e.preventDefault();
      }
      lastTouchEnd = now;
    }, { passive: false });

    document.addEventListener("dblclick", (e) => {
      e.preventDefault();
    }, { passive: false });
  }

  blockZoomHard();

  function updateNetStatus() {
    const el = document.getElementById("net-status");
    if (!el) return;
    const label = el.querySelector("span");
    if (navigator.onLine) {
      el.className = "net-badge net-online";
      if (label) label.textContent = "Онлайн";
    } else {
      el.className = "net-badge net-offline";
      if (label) label.textContent = "Офлайн";
    }
  }
  window.addEventListener("online", updateNetStatus);
  window.addEventListener("offline", updateNetStatus);
  updateNetStatus();

  const userBtn = document.getElementById("app-user-btn");
  const userDropdown = document.getElementById("app-user-dropdown");

  if (userBtn && userDropdown) {
    userBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      const open = userDropdown.hidden;
      userDropdown.hidden = !open;
      userBtn.setAttribute("aria-expanded", open ? "true" : "false");
    });
    document.addEventListener("click", (e) => {
      if (!userDropdown.hidden &&
          !userDropdown.contains(e.target) &&
          e.target !== userBtn) {
        userDropdown.hidden = true;
        userBtn.setAttribute("aria-expanded", "false");
      }
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !userDropdown.hidden) {
        userDropdown.hidden = true;
        userBtn.setAttribute("aria-expanded", "false");
      }
    });
  }

  const FLASH_SHOW_MS = 4000;
  const FLASH_ANIM_MS = 1000;

  function attachFlashBehavior(el) {
    if (!el || el.dataset.flashReady === "1") return;
    el.dataset.flashReady = "1";
    el.classList.add("notice-enter");
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        el.classList.remove("notice-enter");
        el.classList.add("notice-visible");
      });
    });
    const timer = setTimeout(() => {
      el.classList.remove("notice-visible");
      el.classList.add("notice-leave");
      setTimeout(() => {
        if (el.parentNode) el.parentNode.removeChild(el);
      }, FLASH_ANIM_MS);
    }, FLASH_SHOW_MS);
    el.addEventListener("click", () => {
      clearTimeout(timer);
      el.classList.remove("notice-visible");
      el.classList.add("notice-leave");
      setTimeout(() => {
        if (el.parentNode) el.parentNode.removeChild(el);
      }, FLASH_ANIM_MS);
    });
  }

  function initFlashes() {
    document.querySelectorAll("#flash-area .notice").forEach(attachFlashBehavior);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initFlashes);
  } else {
    initFlashes();
  }

  function showFlash(text, type = "info") {
    const area = document.getElementById("flash-area");
    if (!area) return;
    const div = document.createElement("div");
    div.className = `notice notice-${type}`;
    div.textContent = text;
    area.appendChild(div);
    attachFlashBehavior(div);
  }
  window.showFlash = showFlash;

  const SETTINGS_KEY = "app_settings_v1";
  const DEFAULTS = {
    theme: "dark",
    fontSize: "1",
    clockVisible: false,
    clockSeconds: true,
    autoTheme: false,
    largeControls: false,
    highContrast: false,
  };

  let settings = loadSettings();

  function loadSettings() {
    try {
      return Object.assign({}, DEFAULTS,
        JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}"));
    } catch {
      return Object.assign({}, DEFAULTS);
    }
  }
  function saveSettings() {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  }

  function themeForTime(date) {
    const mins = date.getHours() * 60 + date.getMinutes();
    if (mins >= 9 * 60 && mins < 17 * 60) return "light";
    if (mins >= 17 * 60 && mins < 21 * 60) return "gray";
    if (mins >= 21 * 60 || mins < 5 * 60 + 30) return "dark";
    return "gray";
  }

  function applySettings() {
    const html = document.documentElement;
    let theme = settings.theme;
    if (settings.autoTheme) theme = themeForTime(new Date());

    html.dataset.theme = theme;
    html.dataset.fontSize = settings.fontSize;
    html.dataset.largeControls = settings.largeControls ? "true" : "false";
    html.dataset.contrast = settings.highContrast ? "high" : "normal";

    document.querySelectorAll("[data-theme-set]").forEach((b) => {
      const isActive = !settings.autoTheme && b.dataset.themeSet === settings.theme;
      b.classList.toggle("btn-active", isActive);
      b.classList.toggle("btn-outline", !isActive);
      b.classList.toggle("btn-disabled", settings.autoTheme);
    });

    document.querySelectorAll("[data-size-set]").forEach((b) => {
      const isActive = b.dataset.sizeSet === settings.fontSize;
      b.classList.toggle("btn-active", isActive);
      b.classList.toggle("btn-outline", !isActive);
    });

    setChecked("set-clock", settings.clockVisible);
    setChecked("set-clock-seconds", settings.clockSeconds);
    setChecked("set-auto-theme", settings.autoTheme);
    setChecked("set-large-controls", settings.largeControls);
    setChecked("set-high-contrast", settings.highContrast);

    const clock = document.getElementById("app-clock");
    if (clock) clock.hidden = !settings.clockVisible;

    const secCb = document.getElementById("set-clock-seconds");
    if (secCb) {
      secCb.disabled = !settings.clockVisible;
      const row = secCb.closest(".settings-toggle");
      if (row) row.style.opacity = settings.clockVisible ? "1" : "0.45";
    }
  }

  function setChecked(id, value) {
    const el = document.getElementById(id);
    if (el) el.checked = !!value;
  }

  function tick() {
    const now = new Date();

    if (settings.autoTheme) {
      const t = themeForTime(now);
      if (document.documentElement.dataset.theme !== t) {
        document.documentElement.dataset.theme = t;
      }
    }

    if (settings.clockVisible) {
      const el = document.getElementById("app-clock");
      if (el) {
        const hh = String(now.getHours()).padStart(2, "0");
        const mm = String(now.getMinutes()).padStart(2, "0");
        const ss = String(now.getSeconds()).padStart(2, "0");
        el.textContent = settings.clockSeconds
          ? `${hh}:${mm}:${ss}`
          : `${hh}:${mm}`;
      }
    }
  }

  applySettings();
  tick();
  setInterval(tick, 1000);

  const panel = document.getElementById("settings-panel");
  const overlay = document.getElementById("settings-overlay");
  const openBtn = document.getElementById("settings-btn");
  const closeBtn = document.getElementById("settings-close");

  function openPanel() {
    if (!panel) return;
    panel.classList.add("open");
    if (overlay) overlay.classList.add("open");
    panel.setAttribute("aria-hidden", "false");
    if (userDropdown) userDropdown.hidden = true;
  }
  function closePanel() {
    if (!panel) return;
    panel.classList.remove("open");
    if (overlay) overlay.classList.remove("open");
    panel.setAttribute("aria-hidden", "true");
  }

  if (openBtn) openBtn.addEventListener("click", openPanel);
  if (closeBtn) closeBtn.addEventListener("click", closePanel);
  if (overlay) overlay.addEventListener("click", closePanel);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closePanel();
  });

  document.querySelectorAll("[data-theme-set]").forEach((b) => {
    b.addEventListener("click", () => {
      settings.theme = b.dataset.themeSet;
      settings.autoTheme = false;
      saveSettings();
      applySettings();
    });
  });

  document.querySelectorAll("[data-size-set]").forEach((b) => {
    b.addEventListener("click", () => {
      settings.fontSize = b.dataset.sizeSet;
      saveSettings();
      applySettings();
    });
  });

  bindCheckbox("set-clock", "clockVisible");
  bindCheckbox("set-clock-seconds", "clockSeconds");
  bindCheckbox("set-auto-theme", "autoTheme");
  bindCheckbox("set-large-controls", "largeControls");
  bindCheckbox("set-high-contrast", "highContrast");

  function bindCheckbox(id, key) {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener("change", () => {
      settings[key] = el.checked;
      saveSettings();
      applySettings();
      tick();
    });
  }

  const resetBtn = document.getElementById("set-reset");
  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      if (!confirm("Сбросить все настройки на умолчания?")) return;
      settings = Object.assign({}, DEFAULTS);
      saveSettings();
      applySettings();
      tick();
      showFlash("Настройки сброшены", "info");
    });
  }
})();