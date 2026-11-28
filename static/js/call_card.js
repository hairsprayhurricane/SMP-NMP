(function () {
  document.querySelectorAll(".record-item[data-mark-url]").forEach((item) => {
    if (item.classList.contains("record-incorrect")) return;

    let clickTimer = null;
    item.addEventListener("click", (e) => {
      if (e.target.closest("a, button, input, textarea, select, form")) return;

      if (clickTimer) {
        clearTimeout(clickTimer);
        clickTimer = null;

        const ok = confirm("Вы уверены что хотите удалить эту запись? Она будет помечена как «Неверная».");
        if (!ok) return;

        const form = document.createElement("form");
        form.method = "POST";
        form.action = item.dataset.markUrl;

        const csrfMeta = document.querySelector('meta[name="csrf-token"]');
        const csrfInput = document.querySelector('input[name="_csrf"]');
        const csrfValue = csrfMeta ? csrfMeta.content : (csrfInput ? csrfInput.value : "");

        if (csrfValue) {
          const hiddenInput = document.createElement("input");
          hiddenInput.type = "hidden";
          hiddenInput.name = "_csrf";
          hiddenInput.value = csrfValue;
          form.appendChild(hiddenInput);
        }

        document.body.appendChild(form);
        form.submit();
      } else {
        clickTimer = setTimeout(() => {
          clickTimer = null;
        }, 300);
      }
    });
  });
})();