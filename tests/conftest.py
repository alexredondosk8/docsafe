"""Configuración compartida de pytest."""

from pathlib import Path

import pytest

E2E_DIR = Path(__file__).parent / "e2e"


@pytest.fixture(autouse=True)
def isolated_uploads(settings, tmp_path):
    """Cada prueba usa su propia carpeta de subidas, que se descarta al terminar."""
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    settings.UPLOADS_DIR = uploads
    settings.FILE_UPLOAD_TEMP_DIR = str(uploads)
    return uploads


@pytest.fixture(autouse=True)
def no_model_downloads(monkeypatch):
    """Ninguna prueba descarga modelos de internet (se simula donde haga falta)."""
    from apps.conversion import ocr

    def blocked(*args, **kwargs):
        raise OSError("descargas bloqueadas en las pruebas")

    monkeypatch.setattr(ocr.urllib.request, "urlopen", blocked)


def pytest_collection_modifyitems(config, items):
    """Las pruebas e2e (navegador real) van al final y llevan la marca `e2e`.

    Playwright deja un bucle asyncio activo durante el resto de la sesión; al final no
    interfiere con las demás pruebas. Solo e2e: `uv run pytest -m e2e`; sin ellas: `-m "not e2e"`.
    """
    e2e = [item for item in items if E2E_DIR in Path(item.fspath).parents]
    for item in e2e:
        item.add_marker(pytest.mark.e2e)
    items[:] = [item for item in items if item not in e2e] + e2e
