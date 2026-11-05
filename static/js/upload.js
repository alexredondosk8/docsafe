// Validación rápida en el navegador antes de enviar el archivo.
// El servidor vuelve a validar todo: esto solo evita esperas innecesarias.
(function () {
  "use strict";
  const form = document.getElementById("upload-form");
  if (!form) return;
  const input = form.querySelector('input[type="file"]');
  const errorBox = document.getElementById("file-error");
  const button = document.getElementById("upload-button");
  const maxBytes = parseInt(input.dataset.maxBytes, 10);
  const allowed = (input.getAttribute("accept") || "").split(",");

  function showError(message) {
    input.classList.add("is-invalid");
    errorBox.textContent = message;
  }

  function clearError() {
    input.classList.remove("is-invalid");
    errorBox.textContent = "";
  }

  function check() {
    clearError();
    const files = input.files;
    if (!files || files.length === 0) {
      showError("Selecciona un archivo.");
      return false;
    }
    if (files.length > 1) {
      showError("Sube un solo archivo a la vez.");
      return false;
    }
    const file = files[0];
    const dot = file.name.lastIndexOf(".");
    const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : "";
    if (!allowed.includes(ext)) {
      showError("Formato no permitido. Solo se aceptan archivos .pdf, .docx y .xlsx.");
      return false;
    }
    if (file.size === 0) {
      showError("El archivo está vacío.");
      return false;
    }
    if (file.size > maxBytes) {
      const mb = maxBytes / (1024 * 1024);
      showError("El archivo supera el tamaño máximo de " + mb + " MB.");
      return false;
    }
    return true;
  }

  input.addEventListener("change", check);
  form.addEventListener("submit", function (event) {
    if (!check()) {
      event.preventDefault();
      return;
    }
    button.disabled = true;
    button.textContent = "Subiendo…";
  });
})();
