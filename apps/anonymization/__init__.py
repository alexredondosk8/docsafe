"""Anonimización de Markdown: reemplaza datos personales por etiquetas consistentes.

Python puro (sin Django). Capas:
- Fase 4: reglas deterministas (regex y tablas) — ``RegexDetector``, ``detect_in_tables``.
- Fase 6: detector con LLM, que se añade como ``extra_detectors``.
"""

from .anonymizer import Anonymizer, AnonymizerConfig
from .entities import ENTITY_LABELS_ES, Entity, EntityMap, EntityType
from .llm_detector import LLM_TYPES, LLMDetectionStats, LLMDetector
from .review import ReviewData, ReviewEntity, ReviewError, add_term, apply_review, build_review

__all__ = [
    "ENTITY_LABELS_ES",
    "LLM_TYPES",
    "Anonymizer",
    "AnonymizerConfig",
    "Entity",
    "EntityMap",
    "EntityType",
    "LLMDetectionStats",
    "LLMDetector",
    "ReviewData",
    "ReviewEntity",
    "ReviewError",
    "add_term",
    "apply_review",
    "build_review",
]
