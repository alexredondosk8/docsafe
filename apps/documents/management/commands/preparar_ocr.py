"""Descarga y verifica el modelo de OCR (reconocimiento de texto en PDF escaneados).

Uso:  uv run python manage.py preparar_ocr

Solo descarga los pesos del modelo latino de RapidOCR (~8 MB) desde su repositorio oficial y
comprueba su SHA256. Ningún documento sale del equipo. Después el OCR funciona sin internet.
`iniciar` lo hace automáticamente si falta; este comando sirve para prepararlo por adelantado.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.conversion.ocr import OcrUnavailable, download_model, model_path, model_ready


class Command(BaseCommand):
    help = "Descarga y verifica el modelo de OCR para PDF escaneados (una sola vez)."

    def handle(self, *args, **options):
        models_dir = settings.OCR_MODELS_DIR
        if model_ready(models_dir):
            self.stdout.write(
                self.style.SUCCESS(f"El modelo de OCR ya está listo: {model_path(models_dir)}")
            )
            return
        self.stdout.write("Descargando el modelo de OCR (~8 MB, solo esta vez)…")
        try:
            path = download_model(models_dir)
        except OcrUnavailable as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Modelo de OCR listo y verificado: {path}"))
