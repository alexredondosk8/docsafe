"""Capa de servicio para el modelo de lenguaje (LLM).

Un único proveedor configurado solo por variables de entorno (.env):
LLM_BASE_URL, LLM_MODEL, LLM_API_KEY, LLM_TIMEOUT. Usa la API compatible con OpenAI, por lo
que funciona con Ollama (por defecto), LM Studio, vLLM u otros servicios sin cambiar código.

Reglas de seguridad:
- La clave API nunca se devuelve, se muestra ni se registra. Los mensajes de error pasan por
  ``_sanitize`` para quitarla si un servidor la repitiera.
- Las credenciales incrustadas en la URL (usuario:clave@host) se ocultan al mostrarla.
- Los logs nunca incluyen prompts ni respuestas (pueden contener texto de documentos).
"""

import ipaddress
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

import openai

logger = logging.getLogger(__name__)

# Ollama y otros servidores locales no exigen clave, pero la librería necesita un valor.
_PLACEHOLDER_KEY = "sin-clave"
_LOCAL_HOSTNAMES = {"localhost", "localhost.localdomain"}
_MAX_MODELS_SHOWN = 30


class LLMError(Exception):
    """Error al usar el LLM. El mensaje está en español y es seguro mostrarlo al usuario.

    ``kind`` clasifica el error para decidir si reintentar:
    "config", "connection", "auth" (no tiene sentido reintentar) o
    "timeout", "response", "other" (puede funcionar en otro intento).
    """

    def __init__(self, message: str, kind: str = "other") -> None:
        super().__init__(message)
        self.kind = kind

    @property
    def is_fatal(self) -> bool:
        return self.kind in {"config", "connection", "auth"}


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    model: str
    api_key: str = ""
    timeout: float = 120.0
    # "none" desactiva el razonamiento previo de modelos como qwen3 (6 veces más rápido en
    # Ollama con el mismo resultado). Vacío = no se envía el parámetro.
    reasoning_effort: str = ""

    @classmethod
    def from_settings(cls) -> "LLMConfig":
        from django.conf import settings

        return cls(
            base_url=settings.LLM_BASE_URL.strip(),
            model=settings.LLM_MODEL.strip(),
            api_key=settings.LLM_API_KEY,
            timeout=float(settings.LLM_TIMEOUT),
            reasoning_effort=settings.LLM_REASONING_EFFORT.strip(),
        )

    @property
    def extra_body(self) -> dict | None:
        return {"reasoning_effort": self.reasoning_effort} if self.reasoning_effort else None

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)

    @property
    def host(self) -> str:
        return urlsplit(self.base_url).hostname or ""

    @property
    def is_local(self) -> bool:
        return is_local_url(self.base_url)

    @property
    def display_url(self) -> str:
        return mask_url(self.base_url)

    def validation_errors(self) -> list[str]:
        errors = []
        parts = urlsplit(self.base_url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            errors.append(
                "LLM_BASE_URL no es una URL válida (debe empezar por http:// o https://)."
            )
        if not self.model:
            errors.append("Falta LLM_MODEL: indica el nombre del modelo en el archivo .env.")
        if self.timeout <= 0:
            errors.append("LLM_TIMEOUT debe ser un número de segundos mayor que 0.")
        return errors


def is_local_url(url: str) -> bool:
    """True si la URL apunta a este mismo equipo (localhost / 127.x / ::1)."""
    host = (urlsplit(url).hostname or "").lower()
    if host in _LOCAL_HOSTNAMES or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def mask_url(url: str) -> str:
    """Oculta usuario y contraseña si vienen dentro de la URL."""
    parts = urlsplit(url)
    if parts.username or parts.password:
        netloc = "***@" + (parts.hostname or "")
        if parts.port:
            netloc += f":{parts.port}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    return url


@dataclass
class ConnectionResult:
    ok: bool
    message: str
    details: list[str] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    latency_ms: int | None = None


class LLMProvider(Protocol):
    """Interfaz de un proveedor de LLM. Permite añadir otros proveedores más adelante."""

    config: LLMConfig

    def test_connection(self) -> ConnectionResult: ...

    def chat_json(self, system: str, user: str) -> dict: ...


class OpenAICompatibleProvider:
    """Proveedor para cualquier servidor con API compatible con OpenAI (Ollama por defecto)."""

    def __init__(self, config: LLMConfig, http_client=None, max_retries: int = 1) -> None:
        self.config = config
        self._client = openai.OpenAI(
            base_url=config.base_url,
            api_key=config.api_key or _PLACEHOLDER_KEY,
            timeout=config.timeout,
            max_retries=max_retries,
            http_client=http_client,
        )

    # --- Prueba de conexión -------------------------------------------------------------

    def test_connection(self) -> ConnectionResult:
        errors = self.config.validation_errors()
        if errors:
            return ConnectionResult(
                ok=False, message="La configuración está incompleta.", details=errors
            )

        details: list[str] = []
        try:
            models = sorted(m.id for m in self._client.models.list())
        except openai.NotFoundError:
            models = []  # algunos servidores no publican la lista de modelos
            details.append("El servidor no publica la lista de modelos; se omite esa comprobación.")
        except openai.OpenAIError as exc:
            return ConnectionResult(ok=False, message=self._error_message(exc))

        if models:
            details.append(f"Servidor alcanzable: {len(models)} modelos disponibles.")
            if self.config.model not in models:
                return ConnectionResult(
                    ok=False,
                    message=f"El modelo «{self.config.model}» no está disponible en el servidor.",
                    details=[*details, "Revisa LLM_MODEL en .env o descarga el modelo."],
                    models=models[:_MAX_MODELS_SHOWN],
                )
            details.append(f"El modelo «{self.config.model}» está disponible.")

        started = time.monotonic()
        try:
            # Petición mínima que no incluye datos del usuario.
            self._client.chat.completions.create(
                model=self.config.model,
                messages=[{"role": "user", "content": "Responde únicamente: OK"}],
                max_tokens=16,
                temperature=0,
                extra_body=self.config.extra_body,
            )
        except openai.OpenAIError as exc:
            return ConnectionResult(
                ok=False,
                message=self._error_message(exc),
                details=details,
                models=models[:_MAX_MODELS_SHOWN],
            )
        latency = int((time.monotonic() - started) * 1000)
        details.append(f"El modelo respondió en {latency / 1000:.1f} s.")
        return ConnectionResult(
            ok=True,
            message="Conexión correcta con el modelo de lenguaje.",
            details=details,
            models=models[:_MAX_MODELS_SHOWN],
            latency_ms=latency,
        )

    # --- Uso en la anonimización (Fase 6) -----------------------------------------------

    def chat_json(self, system: str, user: str) -> dict:
        """Envía un mensaje y devuelve la respuesta del modelo interpretada como objeto JSON.

        Lanza ``LLMError`` si falla la conexión o la respuesta no es un objeto JSON.
        """
        errors = self.config.validation_errors()
        if errors:
            raise LLMError(" ".join(errors), kind="config")
        try:
            response = self._client.chat.completions.create(
                model=self.config.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0,
                response_format={"type": "json_object"},
                extra_body=self.config.extra_body,
            )
        except openai.OpenAIError as exc:
            raise LLMError(self._error_message(exc), kind=_error_kind(exc)) from None

        content = (response.choices[0].message.content or "") if response.choices else ""
        return parse_json_object(content)

    # --- Errores ------------------------------------------------------------------------

    def _error_message(self, exc: Exception) -> str:
        url = self.config.display_url
        if isinstance(exc, openai.APITimeoutError):
            message = (
                f"El servidor del modelo no respondió a tiempo ({self.config.timeout:g} s). "
                "Aumenta LLM_TIMEOUT o usa un modelo más pequeño."
            )
        elif isinstance(exc, openai.APIConnectionError):
            hint = " ¿Está Ollama en marcha?" if self.config.is_local else ""
            message = f"No se pudo conectar con {url}.{hint}"
        elif isinstance(exc, openai.AuthenticationError | openai.PermissionDeniedError):
            message = "El servidor rechazó la clave API (LLM_API_KEY). Revisa que sea correcta."
        elif isinstance(exc, openai.NotFoundError):
            message = f"El modelo «{self.config.model}» o la ruta de la API no existen en {url}."
        elif isinstance(exc, openai.RateLimitError):
            message = (
                "El servicio del modelo rechazó la petición por límite de uso. Intenta más tarde."
            )
        elif isinstance(exc, openai.APIStatusError):
            message = f"El servidor del modelo devolvió un error (HTTP {exc.status_code})."
        else:
            message = "Error inesperado al comunicarse con el modelo de lenguaje."
        logger.warning("Error del LLM: %s", type(exc).__name__)
        return self._sanitize(message)

    def _sanitize(self, text: str) -> str:
        if self.config.api_key:
            text = text.replace(self.config.api_key, "***")
        return text


def _error_kind(exc: Exception) -> str:
    if isinstance(exc, openai.APITimeoutError):
        return "timeout"
    if isinstance(exc, openai.APIConnectionError):
        return "connection"
    if isinstance(exc, openai.AuthenticationError | openai.PermissionDeniedError):
        return "auth"
    if isinstance(exc, openai.NotFoundError):
        return "config"
    return "other"


_THINK_BLOCK = ("<think>", "</think>")


def parse_json_object(content: str) -> dict:
    """Interpreta la respuesta del modelo como objeto JSON.

    Tolera bloques de razonamiento (<think>…</think>) y cercos de código ```json.
    """
    text = content.strip()
    start_tag, end_tag = _THINK_BLOCK
    if start_tag in text and end_tag in text:
        text = text.split(end_tag, 1)[1].strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[4:] if text.lower().startswith("json") else text
        text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise LLMError("La respuesta del modelo no contiene un objeto JSON.", kind="response")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        raise LLMError("La respuesta del modelo no es un JSON válido.", kind="response") from None
    if not isinstance(data, dict):
        raise LLMError("La respuesta del modelo no es un objeto JSON.", kind="response")
    return data


def get_provider() -> LLMProvider:
    """Proveedor configurado en .env (el único modelo que usa la aplicación)."""
    return OpenAICompatibleProvider(LLMConfig.from_settings())
