"""Datos del LLM disponibles en todas las plantillas (para el aviso de privacidad)."""

from .client import LLMConfig


def llm_privacy(request):
    config = LLMConfig.from_settings()
    return {"llm_is_remote": not config.is_local, "llm_host": config.host}
