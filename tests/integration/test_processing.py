"""Pruebas de integración del procesamiento en segundo plano (django-q2 en modo síncrono)."""

import logging
from pathlib import Path

import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django_q.models import Failure, Success

from apps.conversion import ConversionResult
from apps.documents import pipeline
from apps.documents.models import Conversion

pytestmark = pytest.mark.django_db

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
UPLOAD_URL = reverse("documents:upload")


@pytest.fixture
def upload(client, django_capture_on_commit_callbacks):
    """Sube un archivo de ejemplo y ejecuta la tarea (síncrona) al confirmar la transacción."""

    def _upload(name: str, upload_name: str | None = None) -> Conversion:
        data = (FIXTURES / name).read_bytes()
        file = SimpleUploadedFile(upload_name or name, data)
        with django_capture_on_commit_callbacks(execute=True):
            client.post(UPLOAD_URL, {"file": file})
        return Conversion.objects.get()

    return _upload


def uploads_on_disk() -> list[Path]:
    return [p for p in Path(settings.UPLOADS_DIR).iterdir() if p.is_file()]


# --- Flujo completo ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("contrato.docx", "# Contrato de prestación de servicios"),
        ("empleados.xlsx", "## Hoja: Empleados"),
        ("contrato.pdf", "# Contrato de prestación de servicios"),
    ],
)
def test_subida_procesa_y_completa(upload, name, expected):
    conversion = upload(name)

    assert conversion.status == Conversion.Status.COMPLETED
    assert conversion.progress == 100
    assert conversion.completed_at is not None
    assert expected in conversion.markdown
    assert conversion.error_message == ""


def test_archivo_subido_se_borra_al_terminar(upload):
    conversion = upload("contrato.docx")
    assert conversion.upload.name == ""
    assert uploads_on_disk() == []


def test_avisos_se_guardan(upload):
    conversion = upload("mixto.pdf")
    assert conversion.status == Conversion.Status.COMPLETED
    assert conversion.warnings == [
        "Se omitieron 1 de 2 páginas sin texto (posiblemente escaneadas)."
    ]


@pytest.mark.parametrize(
    ("name", "message"),
    [("escaneado.pdf", "parece escaneado"), ("protegido.pdf", "protegido con contraseña")],
)
def test_error_de_conversion_se_muestra_y_borra_archivo(upload, name, message):
    conversion = upload(name)

    assert conversion.status == Conversion.Status.ERROR
    assert message in conversion.error_message
    assert conversion.markdown == ""
    assert uploads_on_disk() == []


def test_django_q_no_guarda_resultados_ni_trazas(upload):
    upload("contrato.docx")
    upload_error = Conversion.objects.get()
    assert upload_error.status == Conversion.Status.COMPLETED
    assert not Success.objects.exists()
    assert not Failure.objects.exists()


# --- Casos del pipeline -----------------------------------------------------------------


def _pending(tmp_name="x.docx") -> Conversion:
    conversion = Conversion(original_filename=tmp_name, file_type="docx", size_bytes=10)
    conversion.upload.save(tmp_name, SimpleUploadedFile(tmp_name, b"contenido"), save=False)
    conversion.save()
    return conversion


def test_error_inesperado_muestra_mensaje_generico_sin_filtrar_datos(monkeypatch, caplog):
    def boom(path, file_type):
        raise RuntimeError("texto del documento: Juan Pérez C.C. 1.020.304.050")

    monkeypatch.setattr(pipeline, "convert", boom)
    caplog.set_level(logging.DEBUG)
    conversion = _pending()

    pipeline.process(conversion.id)

    conversion.refresh_from_db()
    assert conversion.status == Conversion.Status.ERROR
    assert conversion.error_message == pipeline.GENERIC_ERROR
    assert "RuntimeError" in caplog.text
    assert "Juan" not in caplog.text
    assert "1.020.304.050" not in caplog.text
    assert uploads_on_disk() == []


def test_eliminada_durante_el_procesamiento_no_se_recrea(monkeypatch):
    def convert_and_delete(path, file_type):
        Conversion.objects.filter(file_type="docx").delete()
        return ConversionResult(markdown="# Hola\n")

    monkeypatch.setattr(pipeline, "convert", convert_and_delete)
    conversion = _pending()

    pipeline.process(conversion.id)

    assert not Conversion.objects.exists()
    assert uploads_on_disk() == []


def test_conversion_terminada_no_se_reprocesa(monkeypatch):
    monkeypatch.setattr(pipeline, "convert", lambda *a: pytest.fail("no debe convertir"))
    conversion = Conversion.objects.create(
        original_filename="a.pdf", file_type="pdf", size_bytes=1, status="completed"
    )
    pipeline.process(conversion.id)


def test_conversion_inexistente_no_falla():
    pipeline.process("00000000-0000-0000-0000-000000000000")


def test_archivo_desaparecido_da_error():
    conversion = Conversion.objects.create(original_filename="a.pdf", file_type="pdf", size_bytes=1)
    pipeline.process(conversion.id)
    conversion.refresh_from_db()
    assert conversion.status == Conversion.Status.ERROR
    assert "ya no está disponible" in conversion.error_message


def test_reanuda_conversion_interrumpida(monkeypatch):
    """Si el procesador se cayó a mitad, al reintentar la tarea se procesa de nuevo."""
    monkeypatch.setattr(pipeline, "convert", lambda *a: ConversionResult(markdown="# Ok\n"))
    conversion = _pending()
    Conversion.objects.filter(pk=conversion.pk).update(status="converting", progress=10)

    pipeline.process(conversion.id)

    conversion.refresh_from_db()
    assert conversion.status == Conversion.Status.COMPLETED


def test_reencola_conversiones_sin_terminar(monkeypatch):
    from apps.documents import tasks

    monkeypatch.setattr(pipeline, "convert", lambda *a: ConversionResult(markdown="# Ok\n"))
    pending = _pending("a.docx")
    Conversion.objects.create(
        original_filename="b.pdf", file_type="pdf", size_bytes=1, status="completed"
    )

    assert tasks.requeue_unfinished() == 1  # con sync=True se procesa al instante

    pending.refresh_from_db()
    assert pending.status == Conversion.Status.COMPLETED


def test_pagina_principal_acepta_head(client):
    assert client.head(UPLOAD_URL).status_code == 200


# --- Estado, detalle y descarga ---------------------------------------------------------


def test_estado_json_sin_contenido(client, upload):
    conversion = upload("contrato.docx")
    response = client.get(reverse("documents:status", args=[conversion.id]))

    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    assert response.json() == {
        "status": "completed",
        "status_display": "Completado",
        "progress": 100,
        "is_active": False,
    }


def test_estado_de_conversion_pendiente(client):
    conversion = Conversion.objects.create(original_filename="a.pdf", file_type="pdf", size_bytes=1)
    data = client.get(reverse("documents:status", args=[conversion.id])).json()
    assert data["is_active"] is True
    assert data["status_display"] == "Pendiente"


def test_detalle_activo_consulta_estado(client):
    conversion = Conversion.objects.create(original_filename="a.pdf", file_type="pdf", size_bytes=1)
    content = client.get(reverse("documents:detail", args=[conversion.id])).content.decode()
    assert "js/status.js" in content
    assert reverse("documents:status", args=[conversion.id]) in content


def test_detalle_completado_muestra_vista_previa_reemplazos_y_aviso(client, upload):
    conversion = upload("contrato.docx")
    content = client.get(reverse("documents:detail", args=[conversion.id])).content.decode()

    assert "Vista previa del Markdown" in content
    assert "# Contrato de prestación de servicios No. [CONTRATO_1]" in content
    assert "Anonimización parcial (solo reglas)" in content  # hasta la Fase 6 (LLM)
    assert "Reemplazos realizados" in content
    assert "<code>[CEDULA_1]</code>" in content
    assert "js/status.js" not in content
    for value in ["Juan Carlos", "1.020.304.050", "juan.perez@ejemplo.com", "900.123.456"]:
        assert value not in content


# --- Anonimización en el flujo ----------------------------------------------------------


def test_markdown_guardado_esta_anonimizado(upload):
    conversion = upload("contrato.docx")
    for value in ["Soluciones Andinas", "María Fernanda", "52.345.678", "+57 310 555 1234"]:
        assert value not in conversion.markdown
    assert "[EMPRESA_1]" in conversion.markdown


def test_resumen_de_reemplazos_sin_valores_reales(upload):
    conversion = upload("empleados.xlsx")
    assert conversion.replacements[0] == {
        "type": "NOMBRE",
        "description": "Nombre de persona",
        "label": "[NOMBRE_1]",
        "count": 1,
    }
    serialized = str(conversion.replacements)
    for value in ["Juan", "1.020.304.050", "ejemplo.com", "1985"]:
        assert value not in serialized


def test_tipos_desactivados_desde_settings(settings, upload):
    settings.ANONYMIZATION_DISABLED_TYPES = ["CORREO"]
    conversion = upload("contrato.docx")
    assert "juan.perez@ejemplo.com" in conversion.markdown
    assert "[CEDULA_1]" in conversion.markdown


def test_todas_las_fechas_desde_settings(settings, monkeypatch):
    monkeypatch.setattr(
        pipeline, "convert", lambda *a: ConversionResult(markdown="Firmado el 15/03/2024.\n")
    )
    conversion = _pending()

    settings.ANONYMIZE_ALL_DATES = False
    pipeline.process(conversion.id)
    conversion.refresh_from_db()
    assert conversion.markdown == "Firmado el 15/03/2024.\n"

    second = _pending("y.docx")
    settings.ANONYMIZE_ALL_DATES = True
    pipeline.process(second.id)
    second.refresh_from_db()
    assert second.markdown == "Firmado el [FECHA_1].\n"


def test_detalle_con_error(client, upload):
    conversion = upload("escaneado.pdf")
    content = client.get(reverse("documents:detail", args=[conversion.id])).content.decode()
    assert "No se pudo procesar el documento" in content
    assert "Descargar .md" not in content


def test_vista_previa_escapa_html(client):
    conversion = Conversion.objects.create(
        original_filename="a.pdf",
        file_type="pdf",
        size_bytes=1,
        status="completed",
        markdown="<script>alert(1)</script>",
    )
    content = client.get(reverse("documents:detail", args=[conversion.id])).content.decode()
    assert "<script>alert(1)</script>" not in content
    assert "&lt;script&gt;" in content


def test_descarga_md(client, upload):
    conversion = upload("contrato.docx", upload_name="Contrato año 2024.docx")
    response = client.get(reverse("documents:download", args=[conversion.id]))

    assert response.status_code == 200
    assert response["Content-Type"] == "text/markdown; charset=utf-8"
    assert "attachment" in response["Content-Disposition"]
    assert "Contrato%20a%C3%B1o%202024.md" in response["Content-Disposition"]
    assert b"".join(response.streaming_content).decode() == conversion.markdown


def test_descarga_no_disponible_si_no_esta_completada(client):
    conversion = Conversion.objects.create(original_filename="a.pdf", file_type="pdf", size_bytes=1)
    assert client.get(reverse("documents:download", args=[conversion.id])).status_code == 404
