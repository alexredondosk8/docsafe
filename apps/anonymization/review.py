"""Revisión de reemplazos antes de generar el Markdown final.

1. ``build_review(text, spans)`` agrupa las coincidencias en entidades (una por persona,
   empresa, cédula…) y une variantes de un mismo nombre ("Juan Pérez" ⊂ "Juan Carlos Pérez
   Gómez") o empresa ("Soluciones Andinas" ⊂ "Soluciones Andinas S.A.S.").
2. El usuario desmarca entidades (``enabled=False``) o añade textos con ``add_term``.
3. ``apply_review(text, review)`` reemplaza las entidades marcadas con etiquetas numeradas
   por tipo en orden de aparición y devuelve el texto y un resumen SIN valores reales.

``ReviewData`` contiene valores reales: se guarda solo mientras dura la revisión.
"""

import re
from dataclasses import asdict, dataclass, field

from .entities import ENTITY_LABELS_ES, NUMERIC_TYPES, EntityType, Span, normalize_value

SOURCE_LABELS = {"reglas": "Reglas", "ia": "IA", "usuario": "Añadido por ti"}
_RULE_SOURCES_EXCLUDED = {"ia", "usuario", "propagacion"}


@dataclass
class ReviewEntity:
    key: str
    type: EntityType
    values: list[str]
    sources: list[str]
    count: int = 0
    enabled: bool = True

    def to_dict(self) -> dict:
        data = asdict(self)
        data["type"] = self.type.value
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "ReviewEntity":
        return cls(
            key=data["key"],
            type=EntityType(data["type"]),
            values=list(data["values"]),
            sources=list(data["sources"]),
            count=int(data["count"]),
            enabled=bool(data["enabled"]),
        )

    @property
    def description(self) -> str:
        return ENTITY_LABELS_ES[self.type]

    @property
    def source_labels(self) -> list[str]:
        return [SOURCE_LABELS[s] for s in self.sources if s in SOURCE_LABELS]


@dataclass
class ReviewData:
    entities: list[ReviewEntity] = field(default_factory=list)
    # (inicio, fin, clave de entidad), ordenados y sin solapamientos.
    spans: list[tuple[int, int, str]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "entities": [e.to_dict() for e in self.entities],
            "spans": [list(s) for s in self.spans],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ReviewData":
        return cls(
            entities=[ReviewEntity.from_dict(e) for e in data.get("entities", [])],
            spans=[(int(s), int(e), str(k)) for s, e, k in data.get("spans", [])],
        )

    def entity(self, key: str) -> ReviewEntity | None:
        return next((e for e in self.entities if e.key == key), None)

    def set_enabled(self, enabled_keys: set[str]) -> None:
        for entity in self.entities:
            entity.enabled = entity.key in enabled_keys

    def labels(self) -> dict[str, str]:
        """Etiqueta provisional de cada entidad marcada (numeración por tipo y aparición)."""
        first_seen: dict[str, int] = {}
        for start, _end, key in self.spans:
            first_seen.setdefault(key, start)
        counters: dict[EntityType, int] = {}
        labels = {}
        enabled = [e for e in self.entities if e.enabled and e.key in first_seen]
        for entity in sorted(enabled, key=lambda e: first_seen[e.key]):
            counters[entity.type] = counters.get(entity.type, 0) + 1
            labels[entity.key] = f"[{entity.type.value}_{counters[entity.type]}]"
        return labels


# --- Construcción -----------------------------------------------------------------------


def _source(span: Span) -> str | None:
    if span.source == "propagacion":
        return None
    return span.source if span.source in {"ia", "usuario"} else "reglas"


def build_review(text: str, spans: list[Span]) -> ReviewData:
    """Agrupa las coincidencias (ya sin solapamientos) en entidades revisables."""
    groups: dict[tuple[EntityType, str], dict] = {}
    for span in sorted(spans, key=lambda s: s.start):
        value = text[span.start : span.end]
        key = (span.type, normalize_value(span.type, value))
        group = groups.setdefault(key, {"values": [], "sources": [], "spans": []})
        if value not in group["values"]:
            group["values"].append(value)
        source = _source(span)
        if source and source not in group["sources"]:
            group["sources"].append(source)
        group["spans"].append((span.start, span.end))

    _merge_variants(groups)

    ordered = sorted(groups.items(), key=lambda item: item[1]["spans"][0][0])
    review = ReviewData()
    for index, ((entity_type, _norm), group) in enumerate(ordered, start=1):
        key = f"e{index}"
        review.entities.append(
            ReviewEntity(
                key=key,
                type=entity_type,
                values=group["values"],
                sources=group["sources"] or ["reglas"],
                count=len(group["spans"]),
            )
        )
        review.spans.extend((start, end, key) for start, end in group["spans"])
    review.spans.sort()
    return review


def _merge_variants(groups: dict) -> None:
    """Une variantes de nombres y empresas en la entidad más completa (si no es ambiguo)."""
    for entity_type in (EntityType.NOMBRE, EntityType.EMPRESA):
        keys = sorted((k for k in groups if k[0] == entity_type), key=lambda k: -len(k[1]))
        for short in reversed(keys):
            if short not in groups:
                continue
            candidates = [
                long_
                for long_ in keys
                if long_ != short
                and long_ in groups
                and _is_variant(entity_type, short[1], long_[1])
            ]
            if len(candidates) == 1:
                target = groups[candidates[0]]
                source = groups.pop(short)
                for value in source["values"]:
                    if value not in target["values"]:
                        target["values"].append(value)
                for s in source["sources"]:
                    if s not in target["sources"]:
                        target["sources"].append(s)
                target["spans"] = sorted(target["spans"] + source["spans"])


def _is_variant(entity_type: EntityType, short: str, long_: str) -> bool:
    if len(short) >= len(long_):
        return False
    if entity_type == EntityType.NOMBRE:
        short_tokens, long_tokens = short.split(), long_.split()
        if len(short_tokens) == 1:
            # "Gloria" o "Restrepo" a secas: se une solo si una única persona lo lleva
            # (lo garantiza quien llama: exige un único candidato).
            return len(short_tokens[0]) >= 3 and short_tokens[0] in long_tokens
        return short_tokens[0] == long_tokens[0] and set(short_tokens) <= set(long_tokens)
    return len(short) >= 6 and long_.startswith(short)  # EMPRESA (normalizada sin espacios)


# --- Añadir un dato que se escapó -------------------------------------------------------


class ReviewError(Exception):
    """Mensaje en español para el usuario."""


def _term_pattern(entity_type: EntityType, value: str) -> re.Pattern:
    digits = re.sub(r"\D", "", value)
    if entity_type in NUMERIC_TYPES and len(digits) >= 3 and len(digits) >= len(value) // 2:
        return re.compile(r"(?<!\d)" + r"[.\s-]?".join(digits) + r"(?!\d)")
    body = r"\s+".join(re.escape(w) for w in value.split())
    left = r"(?<!\w)" if value[0].isalnum() else ""
    right = r"(?!\w)" if value[-1].isalnum() else ""
    return re.compile(left + body + right, re.IGNORECASE)


def add_term(text: str, review: ReviewData, value: str, entity_type: EntityType) -> ReviewEntity:
    """Añade un texto a anonimizar en todas sus apariciones. Devuelve la entidad afectada."""
    value = " ".join((value or "").split())
    if len(value) < 2:
        raise ReviewError("Escribe al menos 2 caracteres.")
    if len(value) > 200:
        raise ReviewError("El texto es demasiado largo (máximo 200 caracteres).")
    matches = [(m.start(), m.end()) for m in _term_pattern(entity_type, value).finditer(text)]
    if not matches:
        raise ReviewError("Ese texto no aparece en el documento. Cópialo tal como está escrito.")

    norm = normalize_value(entity_type, value)
    entity = next(
        (
            e
            for e in review.entities
            if e.type == entity_type and norm in {normalize_value(entity_type, v) for v in e.values}
        ),
        None,
    )
    if entity is None:
        numbers = [int(e.key[1:]) for e in review.entities if e.key[1:].isdigit()]
        entity = ReviewEntity(
            key=f"e{max(numbers, default=0) + 1}", type=entity_type, values=[], sources=[]
        )
        review.entities.append(entity)
    entity.enabled = True
    if value not in entity.values:
        entity.values.append(value)
    if "usuario" not in entity.sources:
        entity.sources.append("usuario")

    # Lo añadido por el usuario manda: se quitan las coincidencias que se solapen.
    kept = [
        s for s in review.spans if not any(s[0] < end and start < s[1] for start, end in matches)
    ]
    kept = [s for s in kept if s[2] != entity.key]
    review.spans = sorted(kept + [(start, end, entity.key) for start, end in matches])
    _recount(review)
    return entity


def _recount(review: ReviewData) -> None:
    counts: dict[str, int] = {}
    for _s, _e, key in review.spans:
        counts[key] = counts.get(key, 0) + 1
    review.entities = [e for e in review.entities if counts.get(e.key)]
    for entity in review.entities:
        entity.count = counts[entity.key]


# --- Aplicación -------------------------------------------------------------------------


def apply_review(text: str, review: ReviewData) -> tuple[str, list[dict]]:
    """Texto anonimizado con las entidades marcadas y resumen sin valores reales."""
    labels = review.labels()
    parts, cursor = [], 0
    for start, end, key in review.spans:
        label = labels.get(key)
        if label is None:
            continue
        parts.append(text[cursor:start])
        parts.append(label)
        cursor = end
    parts.append(text[cursor:])

    by_key = {e.key: e for e in review.entities}
    summary = [
        {
            "type": by_key[key].type.value,
            "description": by_key[key].description,
            "label": label,
            "count": by_key[key].count,
        }
        for key, label in labels.items()
    ]
    return "".join(parts), summary
