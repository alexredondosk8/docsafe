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
    "django_q",
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
                "apps.llm.context_processors.llm_privacy",
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
        # El servidor web y el procesador en segundo plano escriben a la vez:
        # WAL permite leer mientras otro escribe y "timeout" espera en vez de fallar.
        "OPTIONS": {
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
            "transaction_mode": "IMMEDIATE",
            "timeout": 20,
        },
    }
}

# --- Tareas en segundo plano (django-q2, broker ORM: sin Redis) -------------------------
# Un solo worker: uso personal y SQLite no gana nada con más concurrencia.
# Regla de privacidad: las tareas solo reciben el id de la conversión y no devuelven nada;
# los errores se capturan dentro de la tarea, así django-q nunca guarda trazas con contenido.
Q_CLUSTER = {
    "name": "docsafe",
    "orm": "default",
    "workers": 1,
    "recycle": 50,
    "timeout": env.int("DOCSAFE_TASK_TIMEOUT", default=1800),  # segundos por documento
    "retry": env.int("DOCSAFE_TASK_TIMEOUT", default=1800) + 60,
    "max_attempts": 1,
    "save_limit": -1,  # no guardar resultados de tareas exitosas
    "ack_failures": True,
    "catch_up": False,
    "poll": 1,
    "label": "Tareas",
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

# --- Mensajes de la interfaz (clases de alerta de Bootstrap) ---------------------------
MESSAGE_TAGS = {40: "danger"}  # messages.ERROR → alert-danger

# --- Límites de subida ------------------------------------------------------------------
MAX_UPLOAD_SIZE_MB = env.int("DOCSAFE_MAX_UPLOAD_MB", default=20)
# Archivos mayores a 2,5 MB se escriben en un temporal dentro de var/ (no en la carpeta
# temporal del sistema), para que todo quede bajo control de la aplicación.
FILE_UPLOAD_TEMP_DIR = str(UPLOADS_DIR)

# --- Anonimización por reglas (Fase 4) ---------------------------------------------------
# Por defecto solo se anonimizan fechas de nacimiento; True reemplaza TODAS las fechas.
ANONYMIZE_ALL_DATES = env.bool("DOCSAFE_ANONIMIZAR_TODAS_LAS_FECHAS", default=False)
# Tipos de dato que NO se anonimizan (separados por comas), p. ej. "EDAD,CUENTA".
ANONYMIZATION_DISABLED_TYPES = [
    t.strip().upper() for t in env.list("DOCSAFE_REGLAS_DESACTIVADAS", default=[]) if t.strip()
]
_VALID_TYPES = {
    "NOMBRE", "CEDULA", "PASAPORTE", "NIT", "EMPRESA", "CORREO", "TELEFONO", "DIRECCION",
    "FECHA_NACIMIENTO", "EDAD", "CONTRATO", "CUENTA", "FECHA",
}  # fmt: skip
_unknown = set(ANONYMIZATION_DISABLED_TYPES) - _VALID_TYPES
if _unknown:
    raise ImproperlyConfigured(
        f"DOCSAFE_REGLAS_DESACTIVADAS contiene tipos desconocidos: {', '.join(sorted(_unknown))}. "
        f"Válidos: {', '.join(sorted(_VALID_TYPES))}."
    )

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
    # Las librerías HTTP/LLM en modo detallado podrían registrar peticiones con contenido.
    "loggers": {
        name: {"level": "WARNING"}
        for name in ("openai", "httpx", "httpx2", "httpcore", "httpcore2")
    },
}
