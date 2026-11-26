(function () {
  // Защита от двойного клика по кнопкам-ссылкам
  document.querySelectorAll('.call-actions .btn').forEach(btn => {
    btn.addEventListener('click', () => {
      btn.classList.add('disabled');
      setTimeout(() => btn.classList.remove('disabled'), 1500);
    });
  });

  // Двойной клик по записи → отметка "Некорректная"
  document.querySelectorAll(".record-item[data-mark-url]").forEach((item) => {
    if (item.classList.contains("record-incorrect")) return;

    let clickTimer = null;
    item.addEventListener("click", (e) => {
      // Игнорируем клики по вложенным интерактивным элементам
      if (e.target.closest("a, button, input, textarea, select")) return;

      if (clickTimer) {
        clearTimeout(clickTimer);
        clickTimer = null;

        const ok = confirm("Отметить эту запись как некорректную?");
        if (!ok) return;

        // Создаём форму для безопасной отправки с CSRF-токеном
        const form = document.createElement("form");
        form.method = "POST";
        form.action = item.dataset.markUrl;
        
        // Берем CSRF-токен из мета-тега или скрытого поля на странице
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