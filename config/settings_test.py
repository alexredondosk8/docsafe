"""Configuración para pruebas automatizadas.

No depende de un archivo .env: define valores seguros antes de cargar la configuración base.
"""

import os
import tempfile

os.environ["DOCSAFE_ENV_FILE"] = os.devnull + ".no-existe"  # ignorar el .env del usuario
os.environ.setdefault("DJANGO_SECRET_KEY", "clave-solo-para-pruebas-no-usar-en-uso-real")
os.environ.setdefault("DOCSAFE_VAR_DIR", tempfile.mkdtemp(prefix="docsafe-test-"))

from .settings import *  # noqa: E402, F403

DEBUG = False
# Las tareas se ejecutan en el mismo proceso, de forma inmediata.
Q_CLUSTER = {**Q_CLUSTER, "sync": True}  # noqa: F405
# En pruebas no se escriben logs a archivo.
LOGGING = {"version": 1, "disable_existing_loggers": False}
