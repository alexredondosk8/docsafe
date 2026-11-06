"""Mantenimiento: archivos subidos que quedaron sin conversión."""

import os
import time

import pytest
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.documents import pipeline, tasks
from apps.documents.models import Conversion
from tests import files

pytestmark = pytest.mark.django_db


def make_old(path, hours=2):
    old = time.time() - hours * 3600
    os.utime(path, (old, old))


def make_conversion(uploads) -> Conversion:
    conversion = Conversion(original_filename="a.pdf", file_type="pdf", size_bytes=10)
    conversion.upload.save("a.pdf", ContentFile(files.pdf_bytes()), save=False)
    conversion.save()
    make_old(uploads / conversion.upload.name)
    return conversion


def test_borra_archivos_huerfanos_antiguos(isolated_uploads):
    orphan = isolated_uploads / "huerfano.pdf"
    temp = isolated_uploads / "tmpabc123.upload"
    for path in (orphan, temp):
        path.write_bytes(b"%PDF-1.4 datos")
        make_old(path)

    assert pipeline.cleanup_orphan_uploads() == 2
    assert list(isolated_uploads.iterdir()) == []


def test_respeta_archivos_de_conversiones_y_recientes(isolated_uploads):
    conversion = make_conversion(isolated_uploads)
    recent = isolated_uploads / "subiendo.pdf"
    recent.write_bytes(b"%PDF-1.4")

    assert pipeline.cleanup_orphan_uploads() == 0
    assert (isolated_uploads / conversion.upload.name).exists()
    assert recent.exists()


def test_mantenimiento_limpia_huerfanos(isolated_uploads, caplog):
    orphan = isolated_uploads / "documento-secreto.pdf"
    orphan.write_bytes(b"%PDF-1.4")
    make_old(orphan)

    tasks.maintenance()

    assert not orphan.exists()
    assert "documento-secreto" not in caplog.text


def test_subida_que_falla_al_guardar_no_deja_archivo(client, isolated_uploads, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("base de datos no disponible")

    monkeypatch.setattr(Conversion, "save", fail)
    client.raise_request_exception = False
    data = files.pdf_bytes()
    response = client.post(reverse("documents:upload"), {"file": SimpleUploadedFile("a.pdf", data)})

    assert response.status_code == 500
    assert [p for p in isolated_uploads.iterdir() if p.suffix == ".pdf"] == []
