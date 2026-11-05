// Consulta periódica del estado de una conversión en curso.
// Actualiza la barra de progreso y recarga la página cuando termina.
(function () {
  "use strict";
  const box = document.getElementById("active-info");
  if (!box) return;
  const url = box.dataset.statusUrl;
  const bar = document.getElementById("progress-bar");
  const progress = document.getElementById("progress");
  const text = document.getElementById("status-text");
  const hint = document.getElementById("stuck-hint");
  const INTERVAL_MS = 1500;
  const STUCK_AFTER_MS = 15000;
  const started = Date.now();

  async function poll() {
    try {
      const response = await fetch(url, { headers: { Accept: "application/json" }, cache: "no-store" });
      if (response.status === 404) {
        window.location.reload(); // se eliminó: la página mostrará el error
        return;
      }
      const data = await response.json();
      bar.style.width = data.progress + "%";
      bar.textContent = data.progress + "%";
      progress.setAttribute("aria-valuenow", data.progress);
      text.textContent = data.status_display + "…";
      if (!data.is_active) {
        window.location.reload();
        return;
      }
      hint.classList.toggle("d-none", !(data.status === "pending" && Date.now() - started > STUCK_AFTER_MS));
    } catch (error) {
      // Servidor detenido momentáneamente: se reintenta en el siguiente ciclo.
    }
    window.setTimeout(poll, INTERVAL_MS);
  }

  window.setTimeout(poll, INTERVAL_MS);
})();
