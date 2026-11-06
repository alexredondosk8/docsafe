"""URLs de CSS/JS con versión según su contenido."""

import hashlib
from functools import lru_cache
from pathlib import Path

from django.contrib.staticfiles import finders
from django.contrib.staticfiles.storage import StaticFilesStorage


@lru_cache(maxsize=256)
def _content_hash(path: str, mtime_ns: int, size: int) -> str:
    # mtime y tamaño forman parte de la clave: si el archivo cambia, se recalcula.
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]


def static_version(name: str) -> str:
    """Huella del contenido del archivo estático, o "" si no existe."""
    path = finders.find(name)
    if not path:
        return ""
    stat = Path(path).stat()
    return _content_hash(str(path), stat.st_mtime_ns, stat.st_size)


class VersionedStaticFilesStorage(StaticFilesStorage):
    """Añade `?v=<huella>` a cada URL de `{% static %}`.

    Sin esto, tras actualizar la aplicación el navegador puede seguir usando el CSS/JS
    antiguo de su caché. No requiere `collectstatic` (whitenoise sirve desde los finders).
    """

    def url(self, name):
        url = super().url(name)
        version = static_version(name)
        return f"{url}?v={version}" if version else url
