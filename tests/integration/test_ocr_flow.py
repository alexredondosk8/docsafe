"""Flujo completo con PDF escaneados (OCR) y página de Configuración (Fase 8)."""

from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.anonymization import apply_review
from apps.conversion.ocr import model_ready
from apps.documents import pipeline
from apps.documents.models import Conversion

pytestmark = pytest.mark.django_db

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REAL_MODELS = Path(__file__).resolve().parents[2] / "var" / "modelos_ocr"
UPLOAD_URL = reverse("documents:upload")

needs_real_ocr = pytest.mark.skipif(
    not model_ready(REAL_MODELS),
    reason="modelo de OCR no descargado (uv run python manage.py preparar_ocr)",
)


@pytest.fixture
def upload(client, django_capture_on_commit_callbacks, settings):
    settings.LLM_ANONYMIZATION_ENABLED = False  # solo reglas: el OCR es lo que se prueba

    def _upload(name: str) -> Conversion:
        file = SimpleUploadedFile(name, (FIXTURES / name).read_bytes())
        with django_capture_on_commit_callbacks(execute=True):
            client.post(UPLOAD_URL, {"file": file})
        return Conversion.objects.get()

    return _upload


@needs_real_ocr
def test_pdf_escaneado_llega_a_revision_sin_fugas(upload, settings, monkeypatch):
    settings.OCR_MODELS_DIR = REAL_MODELS
    messages = []
    original_update = pipeline._update

    def spy(pk, **fields):
        if fields.get("progress_message"):
            messages.append(fields["progress_message"])
        return original_update(pk, **fields)

    monkeypatch.setattr(pipeline, "_update", spy)

    conversion = upload("contrato_escaneado.pdf")

    assert conversion.status == Conversion.Status.REVIEW
    assert "Reconociendo texto (OCR): página 1 de 2" in messages
    assert "Reconociendo texto (OCR): página 2 de 2" in messages
    assert any(w.startswith("Se reconoció texto con OCR en 2 de 2") for w in conversion.warnings)
    out, _ = apply_review(conversion.review_text, pipeline.load_review(conversion))
    for value in ["María Fernanda", "52.345.678", "juan.perez@ejemplo.com", "CPS-2024-0153"]:
        assert value not in out
    assert conversion.upload.name == ""  # el PDF subido se borró


def test_pdf_escaneado_sin_modelo_explica_como_prepararlo(upload, settings, tmp_path):
    settings.OCR_MODELS_DIR = tmp_path / "sin-modelo"
    conversion = upload("contrato_escaneado.pdf")
    assert conversion.status == Conversion.Status.ERROR
    assert "preparar_ocr" in conversion.error_message
    assert "parece escaneado" in conversion.error_message


def test_pdf_escaneado_con_ocr_desactivado(upload, settings):
    settings.OCR_ENABLED = False
    conversion = upload("contrato_escaneado.pdf")
    assert conversion.status == Conversion.Status.ERROR
    assert "DOCSAFE_USAR_OCR=False" in conversion.error_message


def test_opciones_de_ocr_desde_settings(settings, tmp_path):
    settings.OCR_ENABLED = True
    settings.OCR_MODELS_DIR = tmp_path
    settings.OCR_DPI = 250
    settings.OCR_MAX_PAGES = 7
    settings.OCR_MIN_CONFIDENCE = 0.5
    options = pipeline.ocr_options()
    assert (options.models_dir, options.dpi, options.max_pages, options.min_confidence) == (
        tmp_path,
        250,
        7,
        0.5,
    )


# --- Página de Configuración ------------------------------------------------------------


def settings_page(client) -> str:
    return client.get(reverse("llm:settings")).content.decode()


def test_configuracion_ocr_listo(client, settings, monkeypatch):
    from apps.llm import views

    monkeypatch.setattr(views, "model_ready", lambda d: True)
    content = settings_page(client)
    assert "PDF escaneados (OCR)" in content
    assert "Listo · local" in content
    assert "preparar_ocr" not in content


def test_configuracion_ocr_sin_modelo(client, settings, tmp_path):
    settings.OCR_MODELS_DIR = tmp_path
    content = settings_page(client)
    assert "Falta el modelo" in content
    assert "uv run python manage.py preparar_ocr" in content
    assert str(tmp_path) not in content  # no se muestran rutas del disco


def test_configuracion_ocr_desactivado(client, settings):
    settings.OCR_ENABLED = False
    content = settings_page(client)
    assert "Desactivado" in content
    assert "DOCSAFE_USAR_OCR=False" in content


def test_subida_ya_no_dice_que_rechaza_escaneados(client):
    content = client.get(UPLOAD_URL).content.decode()
    assert "No se admiten PDF escaneados" not in content
    assert "reconocimiento de texto (OCR)" in content


def test_comando_preparar_ocr_sin_internet(settings, tmp_path):
    from django.core.management import CommandError, call_command

    settings.OCR_MODELS_DIR = tmp_path / "modelos"
    with pytest.raises(CommandError, match="se necesita internet solo esta vez"):
        call_command("preparar_ocr")


def test_comando_preparar_ocr_ya_listo(settings, monkeypatch, capsys):
    from django.core.management import call_command

    from apps.documents.management.commands import preparar_ocr

    monkeypatch.setattr(preparar_ocr, "model_ready", lambda d: True)
    call_command("preparar_ocr")
    assert "ya está listo" in capsys.readouterr().out
