"""Flujo completo con IA simulada: análisis → pantalla de revisión → confirmar."""

import json
from datetime import timedelta
from pathlib import Path

import httpx2
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.documents import pipeline
from apps.documents.models import Conversion
from tests.llm_fakes import FakeLLMServer, contract_ai_answer

pytestmark = pytest.mark.django_db

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
UPLOAD_URL = reverse("documents:upload")


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
def analyze(client, django_capture_on_commit_callbacks):
    def _analyze(name="contrato.pdf") -> Conversion:
        file = SimpleUploadedFile(name, (FIXTURES / name).read_bytes())
        with django_capture_on_commit_callbacks(execute=True):
            client.post(UPLOAD_URL, {"file": file})
        return Conversion.objects.get()

    return _analyze


def detail(client, conversion):
    return client.get(reverse("documents:detail", args=[conversion.id]))


def post_review(client, conversion, keys, accion):
    return client.post(
        reverse("documents:review_update", args=[conversion.id]),
        {"entidad": keys, "accion": accion},
    )


def keys_except(conversion, *values):
    return [
        e["key"] for e in conversion.review_data["entities"] if not set(e["values"]) & set(values)
    ]


# --- Análisis ---------------------------------------------------------------------------


def test_analisis_deja_la_conversion_en_revision(analyze, fake_ai):
    conversion = analyze()

    assert conversion.status == Conversion.Status.REVIEW
    assert conversion.llm_status == Conversion.LLMStatus.COMPLETE
    assert conversion.markdown == ""  # aún no hay resultado final
    assert "Juan Pérez" in conversion.review_text  # original guardado temporalmente
    assert conversion.upload.name == ""  # el archivo subido ya se borró
    values = [v for e in conversion.review_data["entities"] for v in e["values"]]
    assert "Juan Pérez" in values  # lo encontró la IA (la tabla del anexo)
    assert not conversion.is_active


def test_la_ia_recibe_el_texto_por_fragmentos_y_sin_razonamiento(analyze, fake_ai, settings):
    settings.LLM_CHUNK_CHARS = 400
    analyze()
    chats = [r for r in fake_ai.requests if r.url.path.endswith("/chat/completions")]
    assert len(chats) > 1
    body = json.loads(chats[0].content)
    assert body["reasoning_effort"] == "none"
    assert body["response_format"] == {"type": "json_object"}


def test_variantes_de_nombre_comparten_etiqueta(analyze, fake_ai):
    conversion = analyze()
    entity = next(
        e for e in conversion.review_data["entities"] if "Juan Carlos Pérez Gómez" in e["values"]
    )
    assert "Juan Pérez" in entity["values"]


def test_ia_no_disponible_sigue_con_reglas_y_avisa(analyze, settings, monkeypatch):
    settings.LLM_MODEL = "modelo-prueba"
    server = FakeLLMServer()
    server.error = httpx2.ConnectError("apagado")
    monkeypatch.setattr(pipeline, "get_provider", lambda: server.provider())

    conversion = analyze()

    assert conversion.status == Conversion.Status.REVIEW
    assert conversion.llm_status == Conversion.LLMStatus.FAILED
    assert any("La IA no estaba disponible" in w for w in conversion.warnings)
    assert any("¿Está Ollama en marcha?" in w for w in conversion.warnings)
    assert conversion.review_data["entities"]  # las reglas sí detectaron


def test_ia_desactivada_no_hace_peticiones(analyze, fake_ai, settings):
    settings.LLM_ANONYMIZATION_ENABLED = False
    conversion = analyze()
    assert conversion.llm_status == Conversion.LLMStatus.DISABLED
    assert fake_ai.requests == []


def test_ia_sin_configurar(analyze, settings):
    settings.LLM_MODEL = ""
    conversion = analyze()
    assert conversion.llm_status == Conversion.LLMStatus.NOT_CONFIGURED
    assert any("Falta LLM_MODEL" in w for w in conversion.warnings)


def test_progreso_muestra_fragmentos(fake_ai, settings, monkeypatch):
    from apps.conversion import ConversionResult

    messages = []
    original_update = pipeline._update

    def spy(pk, **fields):
        if fields.get("progress_message"):
            messages.append(fields["progress_message"])
        return original_update(pk, **fields)

    monkeypatch.setattr(pipeline, "_update", spy)
    monkeypatch.setattr(
        pipeline, "convert", lambda *a: ConversionResult(markdown="\n\n".join(["Texto. " * 60] * 3))
    )
    settings.LLM_CHUNK_CHARS = 500
    conversion = Conversion(original_filename="a.docx", file_type="docx", size_bytes=1)
    conversion.upload.save("a.docx", SimpleUploadedFile("a.docx", b"x"), save=False)
    conversion.save()

    pipeline.process(conversion.id)

    assert "Analizando con IA: fragmento 1 de 3" in messages
    assert "Analizando con IA: fragmento 3 de 3" in messages


# --- Pantalla de revisión ---------------------------------------------------------------


def test_pantalla_de_revision_muestra_originales_y_casillas(client, analyze, fake_ai):
    conversion = analyze()
    response = detail(client, conversion)
    content = response.content.decode()

    assert response["Cache-Control"] == "no-store, private"
    assert "Revisa los reemplazos antes de generar el Markdown" in content
    assert "Juan Carlos Pérez Gómez" in content  # valor original visible
    assert 'name="entidad"' in content
    assert "Confirmar y generar Markdown" in content
    assert "IA" in content and "Reglas" in content
    assert "Descargar .md" not in content
    assert "[NOMBRE_1]" in content  # vista previa anonimizada


def test_descarga_no_disponible_en_revision(client, analyze, fake_ai):
    conversion = analyze()
    assert client.get(reverse("documents:download", args=[conversion.id])).status_code == 404


def test_vista_previa_con_seleccion(client, analyze, fake_ai):
    conversion = analyze()
    response = post_review(client, conversion, keys_except(conversion, "Bogotá"), "vista_previa")
    assert response.status_code == 302
    conversion.refresh_from_db()
    assert conversion.status == Conversion.Status.REVIEW
    disabled = [e for e in conversion.review_data["entities"] if not e["enabled"]]
    assert [e["values"] for e in disabled] == [["Bogotá"]]


def test_confirmar_genera_markdown_y_borra_originales(client, analyze, fake_ai):
    conversion = analyze()
    post_review(client, conversion, keys_except(conversion, "Bogotá"), "confirmar")
    conversion.refresh_from_db()

    assert conversion.status == Conversion.Status.COMPLETED
    assert conversion.review_text == ""
    assert conversion.review_data == {}
    assert "Bogotá" in conversion.markdown  # desmarcado: se conserva
    for value in ["Juan Pérez", "María López", "Juan Carlos", "Soluciones Andinas", "52.345.678"]:
        assert value not in conversion.markdown
    assert "Juan" not in str(conversion.replacements)

    content = detail(client, conversion).content.decode()
    assert "Descargar .md" in content
    assert "Juan Carlos Pérez Gómez" not in content


def test_anadir_dato_desde_la_pantalla(client, analyze, fake_ai):
    conversion = analyze()
    response = client.post(
        reverse("documents:review_add", args=[conversion.id]),
        {"valor": "Responsables", "tipo": "NOMBRE"},
    )
    assert response.status_code == 302
    conversion.refresh_from_db()
    added = [e for e in conversion.review_data["entities"] if "usuario" in e["sources"]]
    assert added and added[0]["values"] == ["Responsables"]

    post_review(
        client, conversion, [e["key"] for e in conversion.review_data["entities"]], "confirmar"
    )
    conversion.refresh_from_db()
    assert "Responsables" not in conversion.markdown


def test_anadir_texto_inexistente_muestra_error(client, analyze, fake_ai):
    conversion = analyze()
    response = client.post(
        reverse("documents:review_add", args=[conversion.id]),
        {"valor": "Texto que no existe", "tipo": "NOMBRE"},
        follow=True,
    )
    assert "no aparece en el documento" in response.content.decode()


def test_anadir_tipo_invalido(client, analyze, fake_ai):
    conversion = analyze()
    response = client.post(
        reverse("documents:review_add", args=[conversion.id]),
        {"valor": "Bogotá", "tipo": "INVENTADO"},
        follow=True,
    )
    assert "Elige un tipo de dato válido" in response.content.decode()


def test_acciones_de_revision_solo_en_revision(client):
    conversion = Conversion.objects.create(
        original_filename="a.pdf", file_type="pdf", size_bytes=1, status="completed", markdown="x"
    )
    response = post_review(client, conversion, [], "confirmar")
    assert response.status_code == 302
    conversion.refresh_from_db()
    assert conversion.markdown == "x"


def test_acciones_de_revision_solo_post(client, analyze, fake_ai):
    conversion = analyze()
    assert client.get(reverse("documents:review_update", args=[conversion.id])).status_code == 405
    assert client.get(reverse("documents:review_add", args=[conversion.id])).status_code == 405


def test_descartar_borra_todo(client, analyze, fake_ai):
    conversion = analyze()
    client.post(reverse("documents:delete", args=[conversion.id]))
    assert not Conversion.objects.exists()


# --- Caducidad --------------------------------------------------------------------------


def test_revision_caduca_y_borra_originales(client, analyze, fake_ai, settings):
    settings.REVIEW_EXPIRY_HOURS = 24
    conversion = analyze()
    Conversion.objects.filter(pk=conversion.pk).update(
        updated_at=timezone.now() - timedelta(hours=25)
    )

    content = client.get(reverse("documents:history")).content.decode()

    conversion.refresh_from_db()
    assert conversion.status == Conversion.Status.ERROR
    assert conversion.review_text == ""
    assert conversion.review_data == {}
    assert "caducó" in conversion.error_message
    assert "Error" in content


def test_revision_reciente_no_caduca(analyze, fake_ai):
    conversion = analyze()
    assert pipeline.expire_stale_reviews() == 0
    conversion.refresh_from_db()
    assert conversion.status == Conversion.Status.REVIEW


def test_tarea_periodica_caduca_revisiones(analyze, fake_ai, settings):
    from apps.documents import tasks

    settings.REVIEW_EXPIRY_HOURS = 24
    conversion = analyze()
    Conversion.objects.filter(pk=conversion.pk).update(
        updated_at=timezone.now() - timedelta(hours=25)
    )
    tasks.maintenance()
    conversion.refresh_from_db()
    assert conversion.status == Conversion.Status.ERROR
    assert conversion.review_text == ""


def test_tarea_periodica_no_propaga_errores(monkeypatch, caplog):
    from apps.documents import tasks

    def boom():
        raise RuntimeError("texto secreto")

    monkeypatch.setattr(pipeline, "expire_stale_reviews", boom)
    tasks.maintenance()
    assert "RuntimeError" in caplog.text
    assert "texto secreto" not in caplog.text


def test_mantenimiento_programado_en_django_q():
    from django_q.models import Schedule

    from apps.documents import tasks

    assert not Schedule.objects.filter(name="docsafe-caducar-revisiones").exists()
    schedule = Schedule.objects.get(name="docsafe-mantenimiento")
    assert schedule.func == tasks.MAINTENANCE_PATH
    assert schedule.schedule_type == Schedule.MINUTES
    assert schedule.minutes == 15
    assert schedule.repeats == -1


def test_conversion_en_revision_no_se_reprocesa(analyze, fake_ai, monkeypatch):
    conversion = analyze()
    monkeypatch.setattr(pipeline, "convert", lambda *a: pytest.fail("no debe convertir"))
    pipeline.process(conversion.id)
    conversion.refresh_from_db()
    assert conversion.status == Conversion.Status.REVIEW


def test_logs_sin_valores_reales(analyze, fake_ai, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    analyze()
    for value in ["Juan", "María", "52.345.678", "Soluciones Andinas"]:
        assert value not in caplog.text
