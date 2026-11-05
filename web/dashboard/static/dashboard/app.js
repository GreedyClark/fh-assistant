(function () {
  const tg = window.Telegram && window.Telegram.WebApp;
  if (tg) {
    tg.ready();
    tg.expand();
    try {
      tg.setHeaderColor("#0b0d10");
      tg.setBackgroundColor("#0b0d10");
    } catch (e) {}
    const back = document.body.dataset.back;
    if (back) {
      tg.BackButton.show();
      tg.BackButton.onClick(function () { window.location.href = back; });
    } else {
      tg.BackButton.hide();
    }
  }

  document.querySelectorAll("a[data-external]").forEach(function (link) {
    link.addEventListener("click", function (event) {
      if (tg && tg.openLink) {
        event.preventDefault();
        tg.openLink(link.href);
      }
    });
  });

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
    return Promise.resolve();
  }

  document.querySelectorAll("[data-copy]").forEach(function (button) {
    button.addEventListener("click", function () {
      const source = document.getElementById(button.dataset.copy);
      copyText(source.innerText).then(function () {
        button.textContent = "Скопійовано";
      });
    });
  });

  document.querySelectorAll("form[data-busy]").forEach(function (form) {
    form.addEventListener("submit", function () {
      const button = form.querySelector("button[type=submit]");
      if (button) {
        button.disabled = true;
        button.textContent = form.dataset.busy;
      }
    });
  });

  document.querySelectorAll("[data-fill]").forEach(function (button) {
    button.addEventListener("click", function () {
      const source = document.getElementById(button.dataset.fill);
      const target = document.getElementById(button.dataset.target);
      if (source && target) { target.value = source.innerText.trim(); }
    });
  });

  function confirmText(form) {
    return form.dataset.confirm.replace(/\{(\w+)\}/g, function (_, name) {
      const field = form.elements[name];
      return field ? field.value : "";
    });
  }

  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      const text = confirmText(form);
      const send = function () {
        const button = form.querySelector("button[type=submit]");
        if (button) { button.disabled = true; }
        form.submit();
      };
      if (tg && tg.showConfirm) {
        tg.showConfirm(text, function (ok) { if (ok) { send(); } });
      } else if (window.confirm(text)) {
        send();
      }
    });
  });

  const range = document.getElementById("loud_threshold");
  if (range) {
    const targets = document.querySelectorAll("[data-threshold]");
    const hot = document.querySelector("[data-hot-from]");
    range.addEventListener("input", function () {
      targets.forEach(function (el) { el.textContent = range.value; });
      if (hot) { hot.textContent = Math.max(80, Number(range.value)); }
    });
  }
})();
