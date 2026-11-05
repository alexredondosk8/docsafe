"""Pruebas de la página de Configuración, la prueba de conexión y el aviso de privacidad."""

import pytest
from django.test import Client
from django.urls import reverse

from apps.llm import views
from apps.llm.client import ConnectionResult
from tests.llm_fakes import FakeLLMServer

pytestmark = pytest.mark.django_db

SECRET = "sk-clave-super-secreta-123"
SETTINGS_URL = reverse("llm:settings")
TEST_URL = reverse("llm:test_connection")


@pytest.fixture
def llm(settings):
    settings.LLM_BASE_URL = "http://localhost:11434/v1"
    settings.LLM_MODEL = "qwen3:8b"
    settings.LLM_API_KEY = SECRET
    settings.LLM_TIMEOUT = 60
    return settings


def test_pagina_muestra_configuracion_sin_la_clave(client, llm):
    content = client.get(SETTINGS_URL).content.decode()

    assert "http://localhost:11434/v1" in content
    assert "qwen3:8b" in content
    assert "Local (este equipo)" in content
    assert "Configurada (oculta)" in content
    assert "60 s" in content
    assert SECRET not in content
    assert "sk-" not in content


def test_pagina_sin_clave(client, llm):
    llm.LLM_API_KEY = ""
    assert "No configurada" in client.get(SETTINGS_URL).content.decode()


def test_pagina_es_solo_lectura(client, llm):
    content = client.get(SETTINGS_URL).content.decode()
    assert 'name="LLM_' not in content  # no hay campos para editar
    assert client.post(SETTINGS_URL).status_code == 405


def test_pagina_muestra_errores_de_configuracion(client, llm):
    llm.LLM_MODEL = ""
    content = client.get(SETTINGS_URL).content.decode()
    assert "Falta LLM_MODEL" in content


def test_url_con_credenciales_se_oculta(client, llm):
    llm.LLM_BASE_URL = "https://usuario:otraclave@api.ejemplo.com/v1"
    content = client.get(SETTINGS_URL).content.decode()
    assert "otraclave" not in content
    assert "https://***@api.ejemplo.com/v1" in content


# --- Aviso de privacidad ----------------------------------------------------------------


@pytest.mark.parametrize("url_name", ["documents:upload", "llm:settings"])
def test_aviso_si_el_llm_es_remoto(client, llm, url_name):
    llm.LLM_BASE_URL = "https://api.ejemplo.com/v1"
    content = client.get(reverse(url_name)).content.decode()
    assert "Aviso de privacidad" in content
    assert "api.ejemplo.com" in content
    assert "se enviará a ese servicio" in content


@pytest.mark.parametrize("url_name", ["documents:upload", "llm:settings", "documents:history"])
def test_sin_aviso_si_el_llm_es_local(client, llm, url_name):
    assert "Aviso de privacidad" not in client.get(reverse(url_name)).content.decode()


def test_red_local_cuenta_como_remoto(client, llm):
    llm.LLM_BASE_URL = "http://192.168.1.50:11434/v1"
    content = client.get(reverse("documents:upload")).content.decode()
    assert "Aviso de privacidad" in content


# --- Probar conexión --------------------------------------------------------------------


def test_probar_conexion_devuelve_json_sin_clave(client, llm, monkeypatch):
    server = FakeLLMServer(models=["qwen3:8b"])
    monkeypatch.setattr(
        views, "get_provider", lambda: server.provider(api_key=SECRET, model="qwen3:8b")
    )

    response = client.post(TEST_URL)

    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    data = response.json()
    assert data["ok"] is True
    assert set(data) == {"ok", "message", "details", "models", "latency_ms"}
    assert SECRET not in response.content.decode()


def test_probar_conexion_con_error(client, llm, monkeypatch):
    result = ConnectionResult(
        ok=False, message="No se pudo conectar con http://localhost:11434/v1."
    )
    monkeypatch.setattr(
        views, "get_provider", lambda: type("P", (), {"test_connection": lambda s: result})()
    )
    data = client.post(TEST_URL).json()
    assert data["ok"] is False
    assert "No se pudo conectar" in data["message"]


def test_probar_conexion_solo_post(client, llm):
    assert client.get(TEST_URL).status_code == 405


def test_probar_conexion_requiere_csrf(llm):
    assert Client(enforce_csrf_checks=True).post(TEST_URL).status_code == 403


def test_menu_tiene_configuracion(client, llm):
    assert SETTINGS_URL in client.get(reverse("documents:upload")).content.decode()
