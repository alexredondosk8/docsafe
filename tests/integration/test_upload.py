"""Pruebas de integración: subida, detalle, historial y eliminación."""

import logging
import uuid
from pathlib import Path

import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.documents.models import Conversion
from tests import files

pytestmark = pytest.mark.django_db

UPLOAD_URL = reverse("documents:upload")


def make_file(name: str, data: bytes) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, data, content_type="application/octet-stream")


def upload_path(conversion: Conversion) -> Path:
    return Path(settings.UPLOADS_DIR) / conversion.upload.name


@pytest.mark.parametrize(
    ("name", "data", "file_type"),
    [
        ("informe.pdf", files.pdf_bytes(), "pdf"),
        ("carta.docx", files.docx_bytes(), "docx"),
        ("datos.xlsx", files.xlsx_bytes(), "xlsx"),
    ],
)
def test_subida_valida_crea_conversion_pendiente(client, name, data, file_type):
    response = client.post(UPLOAD_URL, {"file": make_file(name, data)})

    conversion = Conversion.objects.get()
    assert response.status_code == 302
    assert response.url == reverse("documents:detail", args=[conversion.id])
    assert conversion.original_filename == name
    assert conversion.file_type == file_type
    assert conversion.size_bytes == len(data)
    assert conversion.status == Conversion.Status.PENDING
    assert conversion.progress == 0


def test_archivo_se_guarda_con_nombre_aleatorio(client):
    client.post(UPLOAD_URL, {"file": make_file("Contrato Juan Pérez.pdf", files.pdf_bytes())})

    conversion = Conversion.objects.get()
    path = upload_path(conversion)
    assert path.exists()
    assert path.name == f"{conversion.id}.pdf"
    assert path.read_bytes() == files.pdf_bytes()


def test_nombre_con_ruta_se_limpia(client):
    client.post(UPLOAD_URL, {"file": make_file("..\\..\\secreto.pdf", files.pdf_bytes())})
    assert Conversion.objects.get().original_filename == "secreto.pdf"


@pytest.mark.parametrize(
    ("name", "data", "message"),
    [
        ("a.txt", b"hola", "Formato no permitido"),
        ("a.pdf", b"no soy pdf", "no corresponde a un PDF"),
        ("a.docx", files.pdf_bytes(), "no corresponde a un archivo .docx"),
        ("a.pdf", b"", "vacío"),
    ],
)
def test_subida_invalida_muestra_error_y_no_guarda(client, name, data, message):
    response = client.post(UPLOAD_URL, {"file": make_file(name, data)})

    assert response.status_code == 200
    assert message in response.content.decode()
    assert not Conversion.objects.exists()
    assert not any(p.suffix in {".pdf", ".docx"} for p in Path(settings.UPLOADS_DIR).iterdir())


def test_sin_archivo_muestra_error(client):
    response = client.post(UPLOAD_URL, {})
    assert response.status_code == 200
    assert "Selecciona un archivo" in response.content.decode()


def test_rechaza_archivo_mayor_al_limite(client, settings):
    settings.MAX_UPLOAD_SIZE_MB = 1
    data = files.pdf_bytes() + b"0" * (1024 * 1024)
    response = client.post(UPLOAD_URL, {"file": make_file("grande.pdf", data)})

    assert response.status_code == 200
    assert "tamaño máximo de 1 MB" in response.content.decode()
    assert not Conversion.objects.exists()


def test_subida_grande_se_corta_sin_dejar_archivos(client, settings, isolated_uploads):
    """Mayor que el límite y que FILE_UPLOAD_MAX_MEMORY_SIZE: iría a un temporal en disco."""
    from apps.documents.upload_handlers import SizeLimitUploadHandler

    settings.MAX_UPLOAD_SIZE_MB = 1
    received = []
    original = SizeLimitUploadHandler.receive_data_chunk

    def spy(self, raw_data, start):
        received.append(start + len(raw_data))
        return original(self, raw_data, start)

    data = files.pdf_bytes() + b"0" * (3 * 1024 * 1024)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(SizeLimitUploadHandler, "receive_data_chunk", spy)
        response = client.post(UPLOAD_URL, {"file": make_file("grande.pdf", data)})

    assert response.status_code == 200
    assert "tamaño máximo de 1 MB" in response.content.decode()
    assert not Conversion.objects.exists()
    assert list(isolated_uploads.iterdir()) == []  # ni el archivo ni el temporal parcial
    assert max(received) <= 1024 * 1024 + 64 * 1024  # dejó de recibir al pasar el límite


def test_rechaza_varios_archivos(client):
    response = client.post(
        UPLOAD_URL,
        {"file": [make_file("a.pdf", files.pdf_bytes()), make_file("b.pdf", files.pdf_bytes())]},
    )
    assert response.status_code == 200
    assert "un solo archivo a la vez" in response.content.decode()
    assert not Conversion.objects.exists()


def test_formulario_indica_limite_y_formatos(client):
    content = client.get(UPLOAD_URL).content.decode()
    assert 'accept=".pdf,.docx,.xlsx"' in content
    assert f'data-max-bytes="{20 * 1024 * 1024}"' in content


def test_log_no_incluye_nombre_del_archivo(client, caplog):
    caplog.set_level(logging.INFO)
    client.post(UPLOAD_URL, {"file": make_file("Maria_Gomez_cedula.pdf", files.pdf_bytes())})

    assert "creada" in caplog.text
    assert "Maria" not in caplog.text


# --- Detalle e historial ----------------------------------------------------------------


def create_conversion(client, name="informe.pdf") -> Conversion:
    client.post(UPLOAD_URL, {"file": make_file(name, files.pdf_bytes())})
    return Conversion.objects.get(original_filename=name)


def test_detalle_muestra_datos(client):
    conversion = create_conversion(client)
    content = client.get(reverse("documents:detail", args=[conversion.id])).content.decode()
    assert "informe.pdf" in content
    assert "Pendiente" in content


def test_detalle_inexistente_da_404(client):
    response = client.get(reverse("documents:detail", args=[uuid.uuid4()]))
    assert response.status_code == 404


def test_historial_lista_conversiones_recientes_primero(client):
    create_conversion(client, "primero.pdf")
    create_conversion(client, "segundo.pdf")
    content = client.get(reverse("documents:history")).content.decode()
    assert content.index("segundo.pdf") < content.index("primero.pdf")


def test_historial_vacio(client):
    content = client.get(reverse("documents:history")).content.decode()
    assert "Aún no hay conversiones" in content


def test_historial_pagina_de_20_en_20(client):
    for i in range(21):
        Conversion.objects.create(original_filename=f"doc{i}.pdf", file_type="pdf", size_bytes=1)
    content = client.get(reverse("documents:history")).content.decode()
    assert "Página 1 de 2" in content


# --- Eliminación ------------------------------------------------------------------------


def test_eliminar_borra_registro_y_archivo(client):
    conversion = create_conversion(client)
    path = upload_path(conversion)
    assert path.exists()

    response = client.post(reverse("documents:delete", args=[conversion.id]))

    assert response.status_code == 302
    assert not Conversion.objects.exists()
    assert not path.exists()


def test_eliminar_solo_acepta_post(client):
    conversion = create_conversion(client)
    response = client.get(reverse("documents:delete", args=[conversion.id]))
    assert response.status_code == 405
    assert Conversion.objects.exists()


def test_eliminar_requiere_csrf():
    from django.test import Client

    csrf_client = Client(enforce_csrf_checks=True)
    conversion = Conversion.objects.create(original_filename="a.pdf", file_type="pdf", size_bytes=1)
    response = csrf_client.post(reverse("documents:delete", args=[conversion.id]))
    assert response.status_code == 403
    assert Conversion.objects.exists()
