"""Detección en tablas Markdown según el nombre de la columna o de la fila.

- Tabla normal: si la cabecera de una columna es "Nombre", "Cédula", "Correo"… todas las
  celdas de esa columna se consideran ese tipo de dato.
- Tabla clave-valor (2 columnas, primera columna con etiquetas como "NIT", "Empresa"):
  la segunda celda de cada fila se considera del tipo indicado por la primera.
"""

import re
import unicodedata
from dataclasses import dataclass

from .entities import EntityType, Span
from .rules import PRIORITY

_SEPARATOR_ROW = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$")

_HEADER_PATTERNS: list[tuple[EntityType, re.Pattern]] = [
    (
        EntityType.NOMBRE,
        r"nombres?(?: y apellidos| completo| del (?:empleado|trabajador|contratista|cliente))?"
        r"|apellidos?(?: y nombres?)?|responsable|empleado|trabajador|contratista"
        r"|representante(?: legal)?|titular|beneficiario|paciente|funcionario|firmante|persona",
    ),
    (
        EntityType.CEDULA,
        r"(?:(?:no|numero|num|nro) )?(?:de )?(?:cedula(?: de ciudadania)?|cc|c c"
        r"|documento(?: de identidad)?|identificacion|doc)",
    ),
    (EntityType.NIT, r"(?:(?:no|numero|nro) )?(?:de )?nit"),
    (EntityType.PASAPORTE, r"(?:(?:no|numero|nro) )?(?:de )?pasaporte"),
    (EntityType.CORREO, r"correos?(?: electronicos?)?|e ?mails?"),
    (EntityType.TELEFONO, r"telefonos?|tel|celular(?:es)?|cel|movil|whatsapp|contacto telefonico"),
    (EntityType.DIRECCION, r"direccion(?: de residencia)?|domicilio|residencia"),
    (EntityType.FECHA_NACIMIENTO, r"fecha de nacimiento|f nacimiento|nacimiento|fecha nac|f nac"),
    (EntityType.EDAD, r"edad"),
    (EntityType.CONTRATO, r"(?:(?:no|numero|num|nro) )?(?:de )?contrato|contrato (?:no|numero)"),
    (EntityType.EMPRESA, r"empresa|razon social|entidad|compania|proveedor|contratante"),
    (
        EntityType.CUENTA,
        r"(?:(?:no|numero|nro) )?(?:de )?cuenta(?: bancaria| de ahorros| corriente)?",
    ),
]
_HEADER_PATTERNS = [(t, re.compile(rf"^(?:{p})$")) for t, p in _HEADER_PATTERNS]

_EMPTY_VALUES = {"", "-", "—", "n/a", "na", "no aplica", "ninguno", "ninguna", "sin dato", "n.a."}


def _normalize_header(text: str) -> str:
    text = text.replace("\\|", " ")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).casefold()
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())


def header_type(text: str) -> EntityType | None:
    normalized = _normalize_header(text)
    for entity_type, pattern in _HEADER_PATTERNS:
        if pattern.match(normalized):
            return entity_type
    return None


@dataclass
class _Cell:
    start: int
    end: int
    text: str


def _split_cells(line: str, offset: int) -> list[_Cell]:
    """Divide una fila en celdas (respeta '\\|' escapado) con posiciones absolutas."""
    bounds = [i for i, ch in enumerate(line) if ch == "|" and (i == 0 or line[i - 1] != "\\")]
    if not bounds:
        return []
    if line.strip() and not line.lstrip().startswith("|"):
        bounds = [-1, *bounds]
    if line.rstrip() and not line.rstrip().endswith("|") or line.rstrip().endswith("\\|"):
        bounds = [*bounds, len(line)]
    cells = []
    for left, right in zip(bounds, bounds[1:], strict=False):
        raw = line[left + 1 : right]
        stripped = raw.strip()
        lead = len(raw) - len(raw.lstrip())
        start = offset + left + 1 + lead
        cells.append(_Cell(start, start + len(stripped), stripped))
    return cells


def _iter_tables(text: str):
    """Genera tablas como listas de filas (la primera es la cabecera)."""
    lines = text.split("\n")
    offsets, pos = [], 0
    for line in lines:
        offsets.append(pos)
        pos += len(line) + 1

    i = 0
    while i < len(lines) - 1:
        if "|" in lines[i] and _SEPARATOR_ROW.match(lines[i + 1]):
            rows = [_split_cells(lines[i], offsets[i])]
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                rows.append(_split_cells(lines[j], offsets[j]))
                j += 1
            yield rows
            i = j
        else:
            i += 1


def _is_value(cell: _Cell) -> bool:
    return cell.text.casefold() not in _EMPTY_VALUES


def _span(cell: _Cell, entity_type: EntityType) -> Span:
    return Span(cell.start, cell.end, entity_type, priority=PRIORITY[entity_type], source="tabla")


def detect_in_tables(text: str) -> list[Span]:
    spans: list[Span] = []
    for rows in _iter_tables(text):
        header = rows[0]
        width = len(header)
        key_types = [header_type(row[0].text) if row else None for row in rows]
        # Clave-valor: 2 columnas, al menos una fila del cuerpo empieza con una etiqueta
        # conocida y la mitad o más de la primera columna son etiquetas.
        is_key_value = (
            width == 2
            and any(t is not None for t in key_types[1:])
            and sum(t is not None for t in key_types) * 2 >= len(rows)
        )

        if is_key_value:
            for row, entity_type in zip(rows, key_types, strict=True):
                if (
                    entity_type
                    and len(row) >= 2
                    and _is_value(row[1])
                    and header_type(row[1].text) is None
                ):
                    spans.append(_span(row[1], entity_type))
            continue

        column_types = [header_type(cell.text) for cell in header]
        for row in rows[1:]:
            for index, cell in enumerate(row[:width]):
                entity_type = column_types[index]
                if entity_type and _is_value(cell):
                    spans.append(_span(cell, entity_type))
    return spans
