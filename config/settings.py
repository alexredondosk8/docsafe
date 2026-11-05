"""Configuración de Django para DocSafe.

Todos los valores sensibles o propios del equipo se leen de variables de entorno
(archivo .env en la raíz del proyecto). Ver .env.example.
"""

from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
# DOCSAFE_ENV_FILE permite usar otro archivo (las pruebas lo apuntan a uno inexistente).
_env_file = Path(env("DOCSAFE_ENV_FILE", default=str(BASE_DIR / ".env")))
if _env_file.exists():
    # read_env no sobrescribe variables ya definidas en el entorno.
    env.read_env(str(_env_file))

# --- Carpetas de datos de ejecución (no versionadas) ---------------------------------
VAR_DIR = Path(env("DOCSAFE_VAR_DIR", default=str(BASE_DIR / "var")))
UPLOADS_DIR = VAR_DIR / "uploads"
LOGS_DIR = VAR_DIR / "logs"
STATIC_ROOT = VAR_DIR / "staticfiles"
for _dir in (VAR_DIR, UPLOADS_DIR, LOGS_DIR, STATIC_ROOT):
    _dir.mkdir(parents=True, exist_ok=True)

# --- Seguridad --------------------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY", default="")
if not SECRET_KEY:
    raise ImproperlyConfigured(
        "Falta DJANGO_SECRET_KEY. Copia .env.example a .env y define una clave secreta."
    )

DEBUG = env.bool("DJANGO_DEBUG", default=False)

# La aplicación solo atiende peticiones locales: nunca se expone a la red.
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Strict"
SESSION_COOKIE_SAMESITE = "Strict"

# --- Aplicaciones -----------------------------------------------------------------------
# Sin admin ni autenticación: es una aplicación personal de un solo usuario en 127.0.0.1.
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.documents",
    "apps.llm",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Sirve CSS/JS también con DEBUG=False (uso normal), sin servidor web adicional.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Base de datos ----------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": VAR_DIR / "db.sqlite3",
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Idioma y zona horaria --------------------------------------------------------------
LANGUAGE_CODE = "es-co"
TIME_ZONE = env("DOCSAFE_TIME_ZONE", default="America/Bogota")
USE_I18N = True
USE_TZ = True

# --- Archivos estáticos -----------------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
# Sirve directamente desde static/ sin necesidad de ejecutar collectstatic.
WHITENOISE_USE_FINDERS = True

# --- Límites de subida (se usan desde la Fase 1) ----------------------------------------
MAX_UPLOAD_SIZE_MB = env.int("DOCSAFE_MAX_UPLOAD_MB", default=20)

# --- LLM (se usa desde la Fase 5) -------------------------------------------------------
# La clave nunca se envía al navegador ni se muestra en ninguna vista.
LLM_BASE_URL = env("LLM_BASE_URL", default="http://localhost:11434/v1")
LLM_MODEL = env("LLM_MODEL", default="")
LLM_API_KEY = env("LLM_API_KEY", default="")
LLM_TIMEOUT = env.int("LLM_TIMEOUT", default=120)

# --- Registro (logs) --------------------------------------------------------------------
# Regla: NUNCA registrar contenido de documentos ni datos personales.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "{asctime} {levelname} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOGS_DIR / "docsafe.log",
            "maxBytes": 2 * 1024 * 1024,
            "backupCount": 3,
            "encoding": "utf-8",
            "formatter": "simple",
        },
    },
    "root": {"handlers": ["console", "file"], "level": env("DOCSAFE_LOG_LEVEL", default="INFO")},
}
