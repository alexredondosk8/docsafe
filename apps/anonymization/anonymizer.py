"""Motor de anonimización: detecta, propaga, resuelve solapamientos y reemplaza.

Flujo para un texto:
1. Detectores (reglas regex, tablas; en la Fase 6 también el LLM) devuelven fragmentos (spans).
2. Propagación: cada valor detectado se busca en el resto del texto (p. ej. un nombre visto en
   una tabla se reemplaza también en los párrafos).
3. Solapamientos: gana el de mayor prioridad y, a igual prioridad, el más largo.
4. Reemplazo por etiquetas consistentes usando un ``EntityMap`` compartido (el mismo mapa se
   usa para todos los fragmentos de un documento grande).
"""

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .entities import NUMERIC_TYPES, EntityMap, EntityType, Span, normalize_value
from .rules import LEADING_STOPWORDS, Rule, build_rules
from .tables import detect_in_tables

Detector = Callable[[str], Iterable[Span]]

# Tipos que no se propagan: el mismo valor en otra parte no implica el mismo dato.
_NOT_PROPAGATED = {EntityType.EDAD, EntityType.FECHA}
_MIN_TEXT_LENGTH = 4
_MIN_DIGITS = 5


@dataclass(frozen=True)
class AnonymizerConfig:
    disabled_types: frozenset[EntityType] = frozenset()
    anonymize_all_dates: bool = False


class RegexDetector:
    def __init__(self, anonymize_all_dates: bool = False) -> None:
        self.rules: list[Rule] = build_rules(anonymize_all_dates)

    def __call__(self, text: str) -> list[Span]:
        spans = []
        for rule in self.rules:
            for match in rule.pattern.finditer(text):
                start, end = match.span(rule.group)
                if rule.trim_leading_stopwords:
                    start = _skip_leading_stopwords(text, start, end)
                start, end = _strip_edges(text, start, end)
                if end > start:
                    spans.append(Span(start, end, rule.type, rule.priority, source=rule.name))
        return spans


def _skip_leading_stopwords(text: str, start: int, end: int) -> int:
    while True:
        match = re.match(r"(\S+)\s+", text[start:end])
        if not match or match.group(1).casefold().strip(".,") not in LEADING_STOPWORDS:
            return start
        start += match.end()


def _strip_edges(text: str, start: int, end: int) -> tuple[int, int]:
    """Quita espacios y puntuación de los extremos (paréntesis solo si están sin pareja)."""
    while start < end and text[start] in " \t,;:":
        start += 1
    while end > start and text[end - 1] in " \t,;:":
        end -= 1
    if start < end and text[start] == "(" and ")" not in text[start:end]:
        start += 1
    if start < end and text[end - 1] == ")" and "(" not in text[start:end]:
        end -= 1
    return start, end


def _propagation_pattern(entity_type: EntityType, value: str) -> re.Pattern | None:
    if entity_type in _NOT_PROPAGATED:
        return None
    if entity_type in NUMERIC_TYPES:
        digits = normalize_value(entity_type, value)
        if len(digits) < _MIN_DIGITS:
            return None
        body = r"[.\s-]?".join(digits)
        if entity_type == EntityType.NIT:
            body += r"(?:\s?-\s?\d)?"
        elif entity_type == EntityType.TELEFONO:
            body = r"(?:\+?\s?57[\s.-]?)?" + body
        return re.compile(rf"(?<![\d]){body}(?!\d)")
    words = value.split()
    if len(value.strip()) < _MIN_TEXT_LENGTH or not words:
        return None
    body = r"\s+".join(re.escape(w) for w in words)
    return re.compile(rf"(?<!\w){body}(?!\w)", re.IGNORECASE)


def propagate(text: str, spans: list[Span]) -> list[Span]:
    """Añade los demás lugares del texto donde aparece cada valor ya detectado."""
    extra: list[Span] = []
    seen: set[tuple[EntityType, str]] = set()
    for span in spans:
        value = text[span.start : span.end]
        key = (span.type, normalize_value(span.type, value))
        if key in seen:
            continue
        seen.add(key)
        pattern = _propagation_pattern(span.type, value)
        if pattern is None:
            continue
        for match in pattern.finditer(text):
            extra.append(
                Span(match.start(), match.end(), span.type, span.priority - 1, "propagacion")
            )
    return spans + extra


def resolve_overlaps(spans: Iterable[Span]) -> list[Span]:
    accepted: list[Span] = []
    for span in sorted(spans, key=lambda s: (-s.priority, -s.length, s.start)):
        if not any(span.overlaps(other) for other in accepted):
            accepted.append(span)
    return sorted(accepted, key=lambda s: s.start)


def replace_spans(text: str, spans: list[Span], entity_map: EntityMap) -> str:
    """Reemplaza los fragmentos (ya sin solapamientos) por sus etiquetas."""
    labels = [entity_map.label_for(s.type, text[s.start : s.end]) for s in spans]
    parts, cursor = [], 0
    for span, label in zip(spans, labels, strict=True):
        parts.append(text[cursor : span.start])
        parts.append(label)
        cursor = span.end
    parts.append(text[cursor:])
    return "".join(parts)


class Anonymizer:
    """Anonimiza textos con etiquetas consistentes entre llamadas (mismo documento)."""

    def __init__(
        self,
        config: AnonymizerConfig | None = None,
        extra_detectors: Iterable[Detector] = (),
        entity_map: EntityMap | None = None,
    ) -> None:
        self.config = config or AnonymizerConfig()
        self.detectors: list[Detector] = [
            RegexDetector(self.config.anonymize_all_dates),
            detect_in_tables,
            *extra_detectors,
        ]
        self.entity_map = entity_map or EntityMap()

    def find_spans(self, text: str) -> list[Span]:
        spans = [span for detector in self.detectors for span in detector(text)]
        spans = [s for s in spans if s.type not in self.config.disabled_types]
        return resolve_overlaps(propagate(text, spans))

    def anonymize(self, text: str) -> str:
        return replace_spans(text, self.find_spans(text), self.entity_map)
