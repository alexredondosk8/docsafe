"""Tipos de entidad, coincidencias (spans) y mapa de etiquetas consistentes.

La misma entidad recibe siempre la misma etiqueta dentro de un documento: el mapa compara
valores normalizados (p. ej. "1.020.304.050" y "1020304050" son la misma cédula).
El mapa contiene valores reales: vive solo en memoria y nunca se persiste ni se registra.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum


class EntityType(StrEnum):
    NOMBRE = "NOMBRE"
    CEDULA = "CEDULA"
    PASAPORTE = "PASAPORTE"
    NIT = "NIT"
    EMPRESA = "EMPRESA"
    CORREO = "CORREO"
    TELEFONO = "TELEFONO"
    DIRECCION = "DIRECCION"
    FECHA_NACIMIENTO = "FECHA_NACIMIENTO"
    EDAD = "EDAD"
    CONTRATO = "CONTRATO"
    CUENTA = "CUENTA"
    FECHA = "FECHA"


# Descripción en español para la interfaz.
ENTITY_LABELS_ES = {
    EntityType.NOMBRE: "Nombre de persona",
    EntityType.CEDULA: "Documento de identidad",
    EntityType.PASAPORTE: "Pasaporte",
    EntityType.NIT: "NIT",
    EntityType.EMPRESA: "Nombre de empresa",
    EntityType.CORREO: "Correo electrónico",
    EntityType.TELEFONO: "Teléfono",
    EntityType.DIRECCION: "Dirección",
    EntityType.FECHA_NACIMIENTO: "Fecha de nacimiento",
    EntityType.EDAD: "Edad",
    EntityType.CONTRATO: "Número de contrato",
    EntityType.CUENTA: "Cuenta bancaria",
    EntityType.FECHA: "Fecha",
}

# Tipos cuyo valor se compara por sus dígitos.
NUMERIC_TYPES = {
    EntityType.CEDULA,
    EntityType.NIT,
    EntityType.TELEFONO,
    EntityType.CUENTA,
    EntityType.EDAD,
}


@dataclass(frozen=True)
class Span:
    """Un fragmento del texto detectado como dato sensible."""

    start: int
    end: int
    type: EntityType
    # Prioridad para resolver solapamientos de igual longitud (mayor gana).
    priority: int = 0
    source: str = "regex"

    def overlaps(self, other: "Span") -> bool:
        return self.start < other.end and other.start < self.end

    @property
    def length(self) -> int:
        return self.end - self.start


@dataclass
class Entity:
    type: EntityType
    label: str
    # Variantes originales encontradas. SOLO en memoria (pantalla de revisión, Fase 6).
    values: list[str] = field(default_factory=list)
    count: int = 0


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


_COMPANY_SUFFIX = re.compile(r"[\s.,]+")


def normalize_value(entity_type: EntityType, value: str) -> str:
    """Clave de comparación: dos valores con la misma clave son la misma entidad."""
    value = value.strip()
    if entity_type == EntityType.NIT:
        digits = re.sub(r"\D", "", value)
        return digits[:9] if len(digits) >= 9 else digits  # sin dígito de verificación
    if entity_type == EntityType.TELEFONO:
        digits = re.sub(r"\D", "", value)
        return digits[2:] if digits.startswith("57") and len(digits) == 12 else digits
    if entity_type in NUMERIC_TYPES:
        return re.sub(r"\D", "", value)
    if entity_type == EntityType.CORREO:
        return value.lower()
    text = _strip_accents(value).casefold()
    if entity_type == EntityType.EMPRESA:
        return _COMPANY_SUFFIX.sub("", text)
    text = re.sub(r"[^\w#-]+", " ", text)
    return " ".join(text.split())


class EntityMap:
    """Asigna etiquetas consistentes ([TIPO_n]) a los valores detectados."""

    def __init__(self) -> None:
        self._by_key: dict[tuple[EntityType, str], Entity] = {}
        self._counters: dict[EntityType, int] = {}

    def label_for(self, entity_type: EntityType, value: str) -> str:
        key = (entity_type, normalize_value(entity_type, value))
        entity = self._by_key.get(key)
        if entity is None:
            number = self._counters.get(entity_type, 0) + 1
            self._counters[entity_type] = number
            entity = Entity(type=entity_type, label=f"[{entity_type.value}_{number}]")
            self._by_key[key] = entity
        if value not in entity.values:
            entity.values.append(value)
        entity.count += 1
        return entity.label

    @property
    def entities(self) -> list[Entity]:
        return list(self._by_key.values())

    def clear(self) -> None:
        """Borra los valores reales de la memoria (al terminar el procesamiento)."""
        self._by_key.clear()
        self._counters.clear()
