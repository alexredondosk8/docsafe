"""Página de Configuración (solo lectura) y prueba de conexión con el LLM.

La configuración se cambia únicamente en el archivo .env. Ninguna vista devuelve la clave API.
"""

from dataclasses import asdict

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from apps.conversion.ocr import PREPARE_COMMAND, model_ready

from .client import LLMConfig, get_provider


def _ocr_status() -> dict:
    """Estado del OCR para PDF escaneados (sin rutas de disco: no hacen falta en la página)."""
    if not settings.OCR_ENABLED:
        state = "disabled"
    elif model_ready(settings.OCR_MODELS_DIR):
        state = "ready"
    else:
        state = "missing"
    return {
        "state": state,
        "dpi": settings.OCR_DPI,
        "max_pages": settings.OCR_MAX_PAGES,
        "min_confidence": round(settings.OCR_MIN_CONFIDENCE * 100),
        "prepare_command": PREPARE_COMMAND,
    }


@require_GET
def settings_page(request):
    config = LLMConfig.from_settings()
    return render(
        request,
        "llm/settings.html",
        {
            "llm_url": config.display_url,
            "llm_model": config.model,
            "llm_timeout": config.timeout,
            "llm_has_key": config.has_api_key,
            "llm_config_errors": config.validation_errors(),
            "ocr": _ocr_status(),
        },
    )


@require_POST
def test_connection(request):
    result = get_provider().test_connection()
    response = JsonResponse(asdict(result))
    response["Cache-Control"] = "no-store"
    return response
