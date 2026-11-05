"""Página de Configuración (solo lectura) y prueba de conexión con el LLM.

La configuración se cambia únicamente en el archivo .env. Ninguna vista devuelve la clave API.
"""

from dataclasses import asdict

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from .client import LLMConfig, get_provider


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
        },
    )


@require_POST
def test_connection(request):
    result = get_provider().test_connection()
    response = JsonResponse(asdict(result))
    response["Cache-Control"] = "no-store"
    return response
