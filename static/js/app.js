// Comportamiento común de todas las páginas. Sin JavaScript ni estilos en línea en el HTML:
// la Content-Security-Policy no los permite.
(function () {
  "use strict";

  // Ancho de las barras de progreso (style="" en el HTML lo bloquearía la CSP).
  document.querySelectorAll("[data-progress]").forEach(function (bar) {
    bar.style.width = bar.dataset.progress + "%";
  });

  // Confirmación antes de acciones irreversibles: data-confirm en el botón o en el formulario.
  document.addEventListener("click", function (event) {
    const button = event.target.closest("button[data-confirm]");
    if (button && !window.confirm(button.dataset.confirm)) {
      event.preventDefault();
    }
  });
  document.addEventListener("submit", function (event) {
    const form = event.target;
    if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) {
      event.preventDefault();
    }
  });
})();
