"""Configuración compartida de pytest."""

import pytest


@pytest.fixture(autouse=True)
def isolated_uploads(settings, tmp_path):
    """Cada prueba usa su propia carpeta de subidas, que se descarta al terminar."""
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    settings.UPLOADS_DIR = uploads
    settings.FILE_UPLOAD_TEMP_DIR = str(uploads)
    return uploads
