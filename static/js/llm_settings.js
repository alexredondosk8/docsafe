// Botón "Probar conexión" de la página de Configuración.
(function () {
  "use strict";
  const form = document.getElementById("test-connection-form");
  if (!form) return;
  const button = document.getElementById("test-connection-button");
  const output = document.getElementById("test-connection-result");

  function render(data) {
    output.replaceChildren();
    const alert = document.createElement("div");
    alert.className = "alert mb-0 " + (data.ok ? "alert-success" : "alert-danger");
    alert.setAttribute("role", "alert");
    const title = document.createElement("strong");
    title.textContent = data.message;
    alert.appendChild(title);
    if (data.details && data.details.length) {
      const list = document.createElement("ul");
      list.className = "mb-0 mt-2";
      for (const detail of data.details) {
        const item = document.createElement("li");
        item.textContent = detail;
        list.appendChild(item);
      }
      alert.appendChild(list);
    }
    if (!data.ok && data.models && data.models.length) {
      const p = document.createElement("div");
      p.className = "small mt-2";
      p.textContent = "Modelos disponibles: " + data.models.join(", ");
      alert.appendChild(p);
    }
    output.appendChild(alert);
  }

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    button.disabled = true;
    button.textContent = "Probando… (puede tardar si el modelo se está cargando)";
    try {
      const response = await fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        headers: { Accept: "application/json" },
      });
      render(await response.json());
    } catch (error) {
      render({ ok: false, message: "No se pudo completar la prueba. ¿Sigue en marcha la aplicación?" });
    } finally {
      button.disabled = false;
      button.textContent = "Probar conexión";
    }
  });
})();
