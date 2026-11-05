"""Pruebas del cliente LLM con un servidor simulado (sin red)."""

import httpx2
import pytest

from apps.llm.client import LLMConfig, LLMError, is_local_url, mask_url, parse_json_object
from tests.llm_fakes import FakeLLMServer

SECRET = "sk-clave-super-secreta-123"


# --- Local o remoto ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:11434/v1",
        "http://127.0.0.1:1234/v1",
        "http://127.5.5.5/v1",
        "http://[::1]:11434/v1",
        "http://ollama.localhost/v1",
        "HTTP://LOCALHOST:11434/v1",
    ],
)
def test_url_local(url):
    assert is_local_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://api.openai.com/v1",
        "http://192.168.1.10:11434/v1",  # otro equipo de la red: los datos salen del PC
        "http://10.0.0.5/v1",
        "http://localhost.evil.com/v1",
        "http://0.0.0.0:11434/v1",
        "no-es-una-url",
    ],
)
def test_url_remota(url):
    assert not is_local_url(url)


def test_mask_url_oculta_credenciales():
    assert mask_url("https://usuario:clave@api.ejemplo.com:8443/v1") == (
        "https://***@api.ejemplo.com:8443/v1"
    )
    assert mask_url("http://localhost:11434/v1") == "http://localhost:11434/v1"


# --- Validación de configuración --------------------------------------------------------


def test_configuracion_valida():
    assert LLMConfig("http://localhost:11434/v1", "qwen3:8b").validation_errors() == []


def test_configuracion_incompleta():
    errors = LLMConfig("localhost:11434", "", timeout=0).validation_errors()
    assert len(errors) == 3
    assert any("LLM_MODEL" in e for e in errors)
    assert any("LLM_BASE_URL" in e for e in errors)
    assert any("LLM_TIMEOUT" in e for e in errors)


def test_sin_modelo_no_hace_peticiones():
    server = FakeLLMServer()
    result = server.provider(model="").test_connection()
    assert not result.ok
    assert server.requests == []


# --- Probar conexión --------------------------------------------------------------------


def test_conexion_correcta():
    server = FakeLLMServer(models=["otro", "modelo-prueba"])
    result = server.provider().test_connection()

    assert result.ok
    assert result.message == "Conexión correcta con el modelo de lenguaje."
    assert "El modelo «modelo-prueba» está disponible." in result.details
    assert result.latency_ms is not None
    chat = server.last_json()
    assert chat["model"] == "modelo-prueba"
    assert chat["messages"] == [{"role": "user", "content": "Responde únicamente: OK"}]


def test_modelo_no_disponible_lista_los_existentes():
    server = FakeLLMServer(models=["qwen3:8b", "llama3.2:3b"])
    result = server.provider(model="inexistente").test_connection()

    assert not result.ok
    assert "«inexistente» no está disponible" in result.message
    assert result.models == ["llama3.2:3b", "qwen3:8b"]
    assert len(server.requests) == 1  # no intenta chatear


def test_servidor_sin_lista_de_modelos_prueba_igual_el_chat():
    server = FakeLLMServer(models_status=404)
    result = server.provider().test_connection()
    assert result.ok
    assert any("no publica la lista" in d for d in result.details)


def test_servidor_apagado():
    server = FakeLLMServer()
    server.error = httpx2.ConnectError("conexión rechazada")
    result = server.provider().test_connection()
    assert not result.ok
    assert (
        result.message
        == "No se pudo conectar con http://localhost:11434/v1. ¿Está Ollama en marcha?"
    )


def test_servidor_remoto_apagado_sin_pista_de_ollama():
    server = FakeLLMServer()
    server.error = httpx2.ConnectError("conexión rechazada")
    result = server.provider(base_url="https://api.ejemplo.com/v1").test_connection()
    assert "Ollama" not in result.message


def test_tiempo_agotado():
    server = FakeLLMServer()
    server.error = httpx2.ReadTimeout("lento")
    result = server.provider(timeout=5).test_connection()
    assert "no respondió a tiempo (5 s)" in result.message


@pytest.mark.parametrize(
    ("status", "fragment"),
    [
        (401, "rechazó la clave API"),
        (403, "rechazó la clave API"),
        (429, "límite de uso"),
        (500, "HTTP 500"),
    ],
)
def test_errores_http(status, fragment):
    server = FakeLLMServer()
    server.status = status
    result = server.provider(api_key=SECRET).test_connection()
    assert not result.ok
    assert fragment in result.message
    assert SECRET not in str(result)


def test_envia_la_clave_solo_al_servidor_configurado():
    server = FakeLLMServer()
    server.provider(api_key=SECRET).test_connection()
    assert all(r.headers["authorization"] == f"Bearer {SECRET}" for r in server.requests)
    assert all(r.url.host == "localhost" for r in server.requests)


def test_sin_clave_usa_un_valor_neutro():
    server = FakeLLMServer()
    server.provider().test_connection()
    assert server.requests[0].headers["authorization"] == "Bearer sin-clave"


# --- Respuestas JSON (para la Fase 6) ---------------------------------------------------


def test_chat_json():
    server = FakeLLMServer(chat_content='{"entidades": [{"tipo": "NOMBRE", "valor": "Ana"}]}')
    data = server.provider().chat_json("sistema", "texto")

    assert data == {"entidades": [{"tipo": "NOMBRE", "valor": "Ana"}]}
    body = server.last_json()
    assert body["temperature"] == 0
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"][0] == {"role": "system", "content": "sistema"}


def test_chat_json_error_de_conexion_es_fatal():
    server = FakeLLMServer()
    server.error = httpx2.ConnectError("x")
    with pytest.raises(LLMError, match="No se pudo conectar") as info:
        server.provider().chat_json("s", "u")
    assert info.value.kind == "connection"
    assert info.value.is_fatal


@pytest.mark.parametrize(
    ("error", "status", "kind", "fatal"),
    [
        (httpx2.ReadTimeout("lento"), None, "timeout", False),
        (None, 401, "auth", True),
        (None, 404, "config", True),
        (None, 500, "other", False),
    ],
)
def test_chat_json_tipos_de_error(error, status, kind, fatal):
    server = FakeLLMServer()
    server.error, server.status = error, status
    with pytest.raises(LLMError) as info:
        server.provider().chat_json("s", "u")
    assert info.value.kind == kind
    assert info.value.is_fatal is fatal


def test_respuesta_no_json_no_es_fatal():
    server = FakeLLMServer(chat_content="no es json")
    with pytest.raises(LLMError) as info:
        server.provider().chat_json("s", "u")
    assert info.value.kind == "response"
    assert not info.value.is_fatal


def test_desactiva_razonamiento_si_se_configura():
    server = FakeLLMServer(chat_content="{}")
    server.provider(reasoning_effort="none").chat_json("s", "u")
    assert server.last_json()["reasoning_effort"] == "none"


def test_configuracion_lee_razonamiento_de_settings(settings):
    settings.LLM_REASONING_EFFORT = " none "
    assert LLMConfig.from_settings().reasoning_effort == "none"
    assert LLMConfig.from_settings().extra_body == {"reasoning_effort": "none"}


def test_no_envia_razonamiento_si_esta_vacio():
    server = FakeLLMServer(chat_content="{}")
    server.provider(reasoning_effort="").chat_json("s", "u")
    assert "reasoning_effort" not in server.last_json()


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ('{"a": 1}', {"a": 1}),
        ('<think>pienso {"x": 0}</think>\n{"a": 1}', {"a": 1}),
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ('Aquí está: {"a": [1, 2]} fin', {"a": [1, 2]}),
    ],
)
def test_parse_json_object(content, expected):
    assert parse_json_object(content) == expected


@pytest.mark.parametrize("content", ["", "sin json", '{"a": 1', "[1, 2]"])
def test_parse_json_object_invalido(content):
    with pytest.raises(LLMError):
        parse_json_object(content)
