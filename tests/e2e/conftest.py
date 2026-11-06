"""Pruebas de extremo a extremo con un navegador real (Playwright + Chromium).

Usan el servidor en vivo de pytest-django (otro hilo del mismo proceso): las tareas se
ejecutan en el acto (django-q en modo sync) y el LLM está simulado.

Requisito único: `uv run playwright install chromium`. Si falta el navegador, se omiten.
"""

import os
from pathlib import Path

import pytest

from apps.documents import pipeline
from tests.llm_fakes import FakeLLMServer, contract_ai_answer

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture(scope="session", autouse=True)
def _django_sync_with_playwright():
    # La API síncrona de Playwright mantiene un bucle asyncio activo en este hilo y Django
    # bloquearía las consultas del propio test por precaución. Las e2e se ejecutan al final
    # de la suite (tests/conftest.py), así que esto no afecta a las demás pruebas.
    previous = os.environ.get("DJANGO_ALLOW_ASYNC_UNSAFE")
    os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
    yield
    if previous is None:
        os.environ.pop("DJANGO_ALLOW_ASYNC_UNSAFE", None)
    else:
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = previous


@pytest.fixture(scope="session", autouse=True)
def _require_chromium(_django_sync_with_playwright, playwright):
    if not Path(playwright.chromium.executable_path).exists():
        pytest.skip("Chromium no está instalado: uv run playwright install chromium")


@pytest.fixture
def fake_ai(settings, monkeypatch):
    settings.LLM_MODEL = "modelo-prueba"
    settings.LLM_ANONYMIZATION_ENABLED = True
    server = FakeLLMServer(chat_content=contract_ai_answer)
    monkeypatch.setattr(
        pipeline,
        "get_provider",
        lambda: server.provider(reasoning_effort=settings.LLM_REASONING_EFFORT),
    )
    return server


@pytest.fixture
def console_errors(page):
    """Errores de consola y violaciones de CSP durante la prueba."""
    errors = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    return errors
