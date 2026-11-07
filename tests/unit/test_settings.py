"""Pruebas de la configuración base."""

import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings

BASE_DIR = Path(__file__).resolve().parents[2]


def test_solo_acepta_hosts_locales():
    # Se lee del módulo porque pytest-django añade "testserver" a django.conf.settings.
    import config.settings as base

    assert base.ALLOWED_HOSTS == ["127.0.0.1", "localhost"]


def test_idioma_espanol():
    assert settings.LANGUAGE_CODE == "es-co"


def test_limite_de_subida_por_defecto_20_mb():
    assert settings.MAX_UPLOAD_SIZE_MB == 20


def test_llm_por_defecto_apunta_a_ollama_local():
    assert settings.LLM_BASE_URL == "http://localhost:11434/v1"


def test_sin_admin_ni_autenticacion():
    assert "django.contrib.admin" not in settings.INSTALLED_APPS
    assert "django.contrib.auth" not in settings.INSTALLED_APPS


def _import_settings(tmp_path, **extra_env):
    env = {k: v for k, v in os.environ.items() if k != "DJANGO_SECRET_KEY"}
    env["DOCSAFE_VAR_DIR"] = str(tmp_path)
    env["DOCSAFE_ENV_FILE"] = str(tmp_path / "no-existe.env")
    env["PYTHONPATH"] = str(BASE_DIR)
    env.update(extra_env)
    return subprocess.run(  # noqa: S603
        [sys.executable, "-c", "import config.settings"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_falla_si_no_hay_clave_secreta(tmp_path):
    """Sin DJANGO_SECRET_KEY la aplicación no debe arrancar."""
    result = _import_settings(tmp_path)
    assert result.returncode != 0
    assert "DJANGO_SECRET_KEY" in result.stderr


def test_falla_si_la_clave_secreta_esta_vacia(tmp_path):
    result = _import_settings(tmp_path, DJANGO_SECRET_KEY="  ")
    assert result.returncode != 0
    assert "Falta DJANGO_SECRET_KEY" in result.stderr


def test_falla_con_la_clave_de_ejemplo(tmp_path):
    result = _import_settings(tmp_path, DJANGO_SECRET_KEY="cambia-esta-clave")
    assert result.returncode != 0
    assert "valor de ejemplo" in result.stderr


def test_env_example_sin_valores_secretos():
    """La plantilla solo lista los nombres de las variables secretas, sin valores."""
    lines = (BASE_DIR / ".env.example").read_text(encoding="utf-8").splitlines()
    values = dict(line.split("=", 1) for line in lines if line and not line.startswith("#"))
    assert values["DJANGO_SECRET_KEY"] == ""
    assert values["LLM_API_KEY"] == ""


def test_env_no_versionado():
    tracked = subprocess.run(  # noqa: S603
        ["git", "ls-files", ".env"],  # noqa: S607
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    assert tracked.stdout.strip() == ""


def test_falla_con_tipo_de_regla_desconocido(tmp_path):
    result = _import_settings(
        tmp_path, DJANGO_SECRET_KEY="x", DOCSAFE_REGLAS_DESACTIVADAS="CORREO,INVENTADO"
    )
    assert result.returncode != 0
    assert "INVENTADO" in result.stderr


def test_anonimizacion_por_defecto():
    assert settings.ANONYMIZE_ALL_DATES is False
    assert settings.ANONYMIZATION_DISABLED_TYPES == []
