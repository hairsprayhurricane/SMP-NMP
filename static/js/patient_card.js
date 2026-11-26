(function () {
  const btn = document.getElementById("appointment-btn");
  if (!btn) return;
  btn.addEventListener("click", () => {
    btn.classList.add("is-loading");
  });
})();