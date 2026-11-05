"""Detector de datos personales con un modelo de lenguaje (capa 2 de la anonimización).

El modelo NO reescribe el documento: solo devuelve JSON con las entidades que encuentra
(tipo + texto exacto). El código valida cada entidad, comprueba que el texto aparezca de
verdad en el fragmento (descarta invenciones) y calcula sus posiciones.

Python puro: recibe la función que consulta al modelo (``chat_json(system, user) -> dict``),
que lanza excepciones con ``kind`` y ``is_fatal`` (ver ``apps.llm.client.LLMError``).
"""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from .chunking import split_into_chunks
from .entities import EntityType, Span
from .rules import PRIORITY

logger = logging.getLogger(__name__)

ChatJson = Callable[[str, str], dict]
ProgressCallback = Callable[[int, int], None]  # (fragmentos hechos, total)

SOURCE = "ia"

# Tipos que se piden al modelo (FECHA solo si el usuario activó todas las fechas).
LLM_TYPES = [
    EntityType.NOMBRE,
    EntityType.EMPRESA,
    EntityType.DIRECCION,
    EntityType.CEDULA,
    EntityType.PASAPORTE,
    EntityType.NIT,
    EntityType.CORREO,
    EntityType.TELEFONO,
    EntityType.FECHA_NACIMIENTO,
    EntityType.EDAD,
    EntityType.CONTRATO,
    EntityType.CUENTA,
]

# Sinónimos que algunos modelos usan en lugar de los tipos pedidos.
_TYPE_ALIASES = {
    "PERSONA": EntityType.NOMBRE,
    "NOMBRE_PERSONA": EntityType.NOMBRE,
    "PERSON": EntityType.NOMBRE,
    "ORGANIZACION": EntityType.EMPRESA,
    "ORGANIZACIÓN": EntityType.EMPRESA,
    "ORGANIZATION": EntityType.EMPRESA,
    "COMPANIA": EntityType.EMPRESA,
    "ENTIDAD": EntityType.EMPRESA,
    "DOCUMENTO": EntityType.CEDULA,
    "DOCUMENTO_IDENTIDAD": EntityType.CEDULA,
    "EMAIL": EntityType.CORREO,
    "CORREO_ELECTRONICO": EntityType.CORREO,
    "ADDRESS": EntityType.DIRECCION,
    "TEL": EntityType.TELEFONO,
    "CELULAR": EntityType.TELEFONO,
}

_TYPE_HELP = {
    EntityType.NOMBRE: "nombre o apellido de una persona concreta",
    EntityType.EMPRESA: "nombre de una empresa, entidad u organización concreta",
    EntityType.DIRECCION: "dirección física (calle, carrera, avenida, barrio, conjunto, vereda…)",
    EntityType.CEDULA: (
        "NÚMERO de cédula, tarjeta de identidad u otro documento (solo el número, nunca un nombre)"
    ),
    EntityType.PASAPORTE: "número de pasaporte",
    EntityType.NIT: "NIT o número de identificación tributaria",
    EntityType.CORREO: "correo electrónico",
    EntityType.TELEFONO: "número de teléfono o celular (contiene dígitos)",
    EntityType.FECHA_NACIMIENTO: "fecha de nacimiento de una persona",
    EntityType.EDAD: "edad de una persona",
    EntityType.CONTRATO: "número o código de un contrato",
    EntityType.CUENTA: "número de cuenta bancaria",
    EntityType.FECHA: "cualquier fecha",
}

MAX_VALUE_CHARS = 150
MAX_ENTITIES_PER_CHUNK = 200


def build_system_prompt(types: list[EntityType]) -> str:
    lines = "\n".join(f"- {t.value}: {_TYPE_HELP[t]}" for t in types)
    return (
        "Eres un sistema de anonimización de documentos en español (Colombia). "
        "Tu única tarea es encontrar datos personales o confidenciales en el texto que te den.\n\n"
        f"Tipos a buscar:\n{lines}\n\n"
        "Reglas:\n"
        "1. Copia cada valor EXACTAMENTE como aparece en el texto (mismas letras, tildes y "
        "signos), sin añadir ni quitar palabras.\n"
        '2. No incluyas cargos o roles genéricos ("el contratista", "la empresa"), ni '
        "ciudades o países solos, ni montos de dinero.\n"
        "3. Ignora las etiquetas que ya están entre corchetes, como [NOMBRE_1].\n"
        "4. Si un dato aparece varias veces, inclúyelo una sola vez.\n"
        "5. Si no hay datos, devuelve una lista vacía.\n\n"
        'Responde SOLO con un objeto JSON: {"entidades": [{"tipo": "NOMBRE", '
        '"valor": "texto exacto"}]}'
    )


@dataclass
class LLMDetectionStats:
    chunks_total: int = 0
    chunks_ok: int = 0
    chunks_failed: int = 0
    aborted: bool = False
    # Mensaje del último error fatal (en español, sin contenido del documento).
    abort_reason: str = ""
    entities_discarded: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        """ "completo", "parcial" o "fallido"."""
        if self.chunks_total and self.chunks_ok == self.chunks_total:
            return "completo"
        if self.chunks_ok:
            return "parcial"
        return "fallido"


class LLMDetector:
    """Detector para ``Anonymizer(extra_detectors=[...])``."""

    def __init__(
        self,
        chat_json: ChatJson,
        chunk_chars: int = 2500,
        types: list[EntityType] | None = None,
        max_retries: int = 2,
        max_consecutive_failures: int = 3,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        self.chat_json = chat_json
        self.chunk_chars = chunk_chars
        self.types = types or LLM_TYPES
        self.max_retries = max_retries
        self.max_consecutive_failures = max_consecutive_failures
        self.on_progress = on_progress
        self.stats = LLMDetectionStats()
        self.system_prompt = build_system_prompt(self.types)

    def __call__(self, text: str) -> list[Span]:
        chunks = split_into_chunks(text, self.chunk_chars)
        self.stats = LLMDetectionStats(chunks_total=len(chunks))
        spans: list[Span] = []
        consecutive_failures = 0
        for index, chunk in enumerate(chunks, start=1):
            if self.on_progress:
                self.on_progress(index - 1, len(chunks))
            try:
                entities = self._ask(chunk.text)
            except Exception as exc:  # noqa: BLE001 - se decide según el tipo de error
                self.stats.chunks_failed += 1
                consecutive_failures += 1
                message = str(exc) if getattr(exc, "kind", None) else "Error inesperado."
                self.stats.errors.append(message)
                logger.warning("IA: fragmento %d/%d falló (%s)", index, len(chunks), _kind(exc))
                if getattr(exc, "is_fatal", False) or (
                    consecutive_failures >= self.max_consecutive_failures
                ):
                    self.stats.aborted = True
                    self.stats.abort_reason = message
                    self.stats.chunks_failed = len(chunks) - self.stats.chunks_ok
                    break
                continue
            consecutive_failures = 0
            self.stats.chunks_ok += 1
            spans.extend(self._locate(chunk.text, chunk.start, entities))
        if self.on_progress:
            self.on_progress(len(chunks), len(chunks))
        return spans

    # --- Consulta y validación ----------------------------------------------------------

    def _ask(self, chunk_text: str) -> list[tuple[EntityType, str]]:
        user = f"Texto:\n<<<\n{chunk_text}\n>>>"
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            prompt = user
            if attempt:
                prompt += (
                    "\n\nTu respuesta anterior no era válida. Devuelve SOLO el objeto JSON "
                    '{"entidades": [...]} con "tipo" y "valor" en cada elemento.'
                )
            try:
                data = self.chat_json(self.system_prompt, prompt)
                return self._validate(data)
            except Exception as exc:  # noqa: BLE001
                if getattr(exc, "is_fatal", False):
                    raise
                last_error = exc
        raise last_error  # type: ignore[misc]

    def _validate(self, data: dict) -> list[tuple[EntityType, str]]:
        items = data.get("entidades", data.get("entities"))
        if not isinstance(items, list):
            raise _ResponseError('La respuesta del modelo no tiene la lista "entidades".')
        result = []
        for item in items[:MAX_ENTITIES_PER_CHUNK]:
            if not isinstance(item, dict):
                self.stats.entities_discarded += 1
                continue
            raw_type = str(item.get("tipo", item.get("type", ""))).strip().upper()
            value = item.get("valor", item.get("value"))
            entity_type = _parse_type(raw_type)
            if entity_type is not None and _valid_value(value):
                entity_type = _fix_type(entity_type, value.strip())
            if entity_type is None or entity_type not in self.types or not _valid_value(value):
                self.stats.entities_discarded += 1
                continue
            result.append((entity_type, value.strip()))
        return result

    def _locate(
        self, chunk_text: str, offset: int, entities: list[tuple[EntityType, str]]
    ) -> list[Span]:
        spans = []
        for entity_type, value in entities:
            pattern = _value_pattern(value)
            matches = list(pattern.finditer(chunk_text))
            if not matches:  # el modelo inventó o alteró el texto: se descarta
                self.stats.entities_discarded += 1
                continue
            priority = PRIORITY[entity_type] - 2  # las reglas ganan en empates
            for match in matches:
                spans.append(
                    Span(
                        offset + match.start(), offset + match.end(), entity_type, priority, SOURCE
                    )
                )
        return spans


class _ResponseError(Exception):
    kind = "response"
    is_fatal = False


def _kind(exc: Exception) -> str:
    return getattr(exc, "kind", type(exc).__name__)


def _parse_type(raw: str) -> EntityType | None:
    raw = raw.replace(" ", "_")
    try:
        return EntityType(raw)
    except ValueError:
        return _TYPE_ALIASES.get(raw)


_DIGIT_TYPES = {
    EntityType.CEDULA,
    EntityType.PASAPORTE,
    EntityType.NIT,
    EntityType.TELEFONO,
    EntityType.EDAD,
    EntityType.CUENTA,
    EntityType.FECHA_NACIMIENTO,
    EntityType.FECHA,
}
_PERSON_NAME = re.compile(r"[A-ZÁÉÍÓÚÑÜ][\wáéíóúñü'.-]*(?:\s+[\wáéíóúñü'.-]+){0,5}")


def _fix_type(entity_type: EntityType, value: str) -> EntityType | None:
    """Corrige tipos numéricos sin dígitos (p. ej. un nombre marcado como CEDULA).

    Si parece un nombre propio se trata como NOMBRE (mejor anonimizar de más); si no, se descarta.
    """
    if entity_type not in _DIGIT_TYPES or re.search(r"\d", value):
        return entity_type
    words = value.split()
    looks_like_name = _PERSON_NAME.fullmatch(value) and all(
        w[0].isupper() or w.lower() in {"de", "del", "la", "las", "los", "y"} for w in words
    )
    return EntityType.NOMBRE if looks_like_name else None


def _valid_value(value) -> bool:
    if not isinstance(value, str):
        return False
    value = value.strip()
    if len(value) < 2 or len(value) > MAX_VALUE_CHARS or "\n" in value:
        return False
    return not re.fullmatch(r"\[[A-Z_]+_\d+\]", value)  # una etiqueta ya puesta


def _value_pattern(value: str) -> re.Pattern:
    """Busca el valor tal cual (espacios flexibles, sin distinguir mayúsculas)."""
    body = r"[ \t]+".join(re.escape(word) for word in value.split())
    left = r"(?<!\w)" if value[0].isalnum() else ""
    right = r"(?!\w)" if value[-1].isalnum() else ""
    return re.compile(left + body + right, re.IGNORECASE)
