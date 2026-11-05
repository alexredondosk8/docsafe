"""Pruebas del detector con LLM usando un modelo simulado (sin red)."""

import pytest

from apps.anonymization import Anonymizer, EntityType, LLMDetector
from apps.anonymization.llm_detector import build_system_prompt
from apps.llm.client import LLMError

T = EntityType

TEXT = (
    "La reunión con Laura Gómez de Tecnologías Delta se hizo en la avenida Boyacá con "
    "calle 80. También asistió Andrés Mejía."
)


class FakeModel:
    """Devuelve respuestas programadas; registra las llamadas."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def __call__(self, system: str, user: str) -> dict:
        self.calls.append((system, user))
        response = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(response, Exception):
            raise response
        if callable(response):
            return response(user)
        return response


def entities(*pairs):
    return {"entidades": [{"tipo": t, "valor": v} for t, v in pairs]}


def found(text, spans):
    return sorted((s.type, text[s.start : s.end]) for s in spans)


def test_detecta_y_ubica_entidades():
    model = FakeModel(
        entities(
            ("NOMBRE", "Laura Gómez"),
            ("EMPRESA", "Tecnologías Delta"),
            ("DIRECCION", "avenida Boyacá con calle 80"),
            ("NOMBRE", "Andrés Mejía"),
        )
    )
    detector = LLMDetector(model)
    spans = detector(TEXT)

    assert found(TEXT, spans) == sorted(
        [
            (T.NOMBRE, "Laura Gómez"),
            (T.EMPRESA, "Tecnologías Delta"),
            (T.DIRECCION, "avenida Boyacá con calle 80"),
            (T.NOMBRE, "Andrés Mejía"),
        ]
    )
    assert all(s.source == "ia" for s in spans)
    assert detector.stats.status == "completo"


def test_descarta_valores_inventados_y_tipos_desconocidos():
    model = FakeModel(
        entities(
            ("NOMBRE", "Pedro Inventado"),  # no está en el texto
            ("COLOR", "azul"),  # tipo desconocido
            ("NOMBRE", "[NOMBRE_1]"),  # etiqueta ya puesta
            ("NOMBRE", "x"),  # demasiado corto
            ("PERSONA", "Laura Gómez"),  # sinónimo aceptado
        )
    )
    detector = LLMDetector(model)
    spans = detector(TEXT)
    assert found(TEXT, spans) == [(T.NOMBRE, "Laura Gómez")]
    assert detector.stats.entities_discarded == 4


def test_nombre_marcado_como_tipo_numerico_se_reclasifica():
    """Visto con qwen3:8b real: devolvió nombres de una tabla como CEDULA."""
    model = FakeModel(
        entities(
            ("CEDULA", "Laura Gómez"),  # nombre propio → NOMBRE
            ("TELEFONO", "Andrés Mejía"),  # nombre propio → NOMBRE
            ("CEDULA", "la reunión"),  # sin dígitos ni nombre → se descarta
        )
    )
    detector = LLMDetector(model)
    assert found(TEXT, detector(TEXT)) == [(T.NOMBRE, "Andrés Mejía"), (T.NOMBRE, "Laura Gómez")]
    assert detector.stats.entities_discarded == 1


def test_tipos_no_pedidos_se_ignoran():
    model = FakeModel(entities(("CORREO", "a@b.co"), ("NOMBRE", "Laura Gómez")))
    detector = LLMDetector(model, types=[T.NOMBRE])
    assert found(TEXT + " a@b.co", detector(TEXT + " a@b.co")) == [(T.NOMBRE, "Laura Gómez")]


def test_encuentra_todas_las_apariciones_sin_distinguir_mayusculas():
    text = "Laura Gómez firmó. LAURA GÓMEZ aprobó."
    detector = LLMDetector(FakeModel(entities(("NOMBRE", "Laura Gómez"))))
    assert len(detector(text)) == 2


def test_reintenta_si_la_respuesta_no_es_valida():
    model = FakeModel(
        LLMError("no es JSON", kind="response"),
        {"otra_cosa": []},
        entities(("NOMBRE", "Laura Gómez")),
    )
    detector = LLMDetector(model, max_retries=2)
    spans = detector(TEXT)
    assert found(TEXT, spans) == [(T.NOMBRE, "Laura Gómez")]
    assert len(model.calls) == 3
    assert "no era válida" in model.calls[1][1]


def test_fragmento_fallido_se_omite_y_continua():
    paragraphs = ["Uno con Laura Gómez. " * 5, "Dos con Andrés Mejía. " * 5]
    text = "\n\n".join(paragraphs)

    def answer(user):
        if "Laura" in user:
            raise LLMError("tiempo", kind="timeout")
        return entities(("NOMBRE", "Andrés Mejía"))

    detector = LLMDetector(FakeModel(answer), chunk_chars=120, max_retries=1)
    spans = detector(text)
    assert {text[s.start : s.end] for s in spans} == {"Andrés Mejía"}
    assert detector.stats.chunks_failed == 1
    assert detector.stats.status == "parcial"
    assert not detector.stats.aborted


def test_error_fatal_detiene_la_ia():
    text = "\n\n".join(["Párrafo con Laura Gómez. " * 5] * 4)
    model = FakeModel(LLMError("No se pudo conectar con http://localhost:11434/v1.", "connection"))
    detector = LLMDetector(model, chunk_chars=150)
    assert detector(text) == []
    assert detector.stats.aborted
    assert detector.stats.status == "fallido"
    assert "No se pudo conectar" in detector.stats.abort_reason
    assert len(model.calls) == 1  # no insiste fragmento tras fragmento


def test_varios_fallos_seguidos_detienen_la_ia():
    text = "\n\n".join(["Párrafo con Laura Gómez. " * 5] * 6)
    model = FakeModel(LLMError("tiempo", kind="timeout"))
    detector = LLMDetector(model, chunk_chars=150, max_retries=0, max_consecutive_failures=3)
    detector(text)
    assert detector.stats.aborted
    assert len(model.calls) == 3


def test_posiciones_correctas_en_fragmentos_posteriores():
    text = "Relleno sin datos. " * 20 + "\n\nAl final firma Andrés Mejía."
    detector = LLMDetector(
        FakeModel(
            lambda user: entities(("NOMBRE", "Andrés Mejía")) if "Andrés" in user else entities()
        ),
        chunk_chars=200,
    )
    spans = detector(text)
    assert [text[s.start : s.end] for s in spans] == ["Andrés Mejía"]


def test_informa_progreso():
    calls = []
    text = "\n\n".join(["Párrafo de relleno. " * 5] * 3)
    LLMDetector(
        FakeModel(entities()), chunk_chars=120, on_progress=lambda d, t: calls.append((d, t))
    )(text)
    total = calls[-1][1]
    assert calls[0] == (0, total)
    assert calls[-1] == (total, total)


def test_cancelacion_se_propaga():
    class Cancelled(Exception):
        pass

    def on_progress(done, total):
        raise Cancelled

    with pytest.raises(Cancelled):
        LLMDetector(FakeModel(entities()), on_progress=on_progress)(TEXT)


def test_prompt_pide_json_y_copiar_exacto():
    prompt = build_system_prompt([T.NOMBRE, T.DIRECCION])
    assert '"entidades"' in prompt
    assert "EXACTAMENTE" in prompt
    assert "- NOMBRE:" in prompt and "- DIRECCION:" in prompt
    assert "CORREO" not in prompt


def test_integrado_con_reglas_y_propagacion():
    text = (
        "Laura Gómez (C.C. 52.345.678) vive en la avenida Boyacá con calle 80.\n\n"
        "Firmó Laura Gómez."
    )
    model = FakeModel(
        entities(("NOMBRE", "Laura Gómez"), ("DIRECCION", "avenida Boyacá con calle 80"))
    )
    out = Anonymizer(extra_detectors=[LLMDetector(model)]).anonymize(text)
    assert out == "[NOMBRE_1] (C.C. [CEDULA_1]) vive en la [DIRECCION_1].\n\nFirmó [NOMBRE_1]."
