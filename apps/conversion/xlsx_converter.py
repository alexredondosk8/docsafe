"""Excel (.xlsx) → Markdown con openpyxl.

Cada hoja se convierte en una sección ``## Hoja: <nombre>`` con una tabla Markdown cuya
primera fila es la cabecera. Se usan los valores calculados de las fórmulas (los que Excel
guardó en el archivo). Se eliminan filas y columnas completamente vacías.
Las hojas ocultas se incluyen y se marcan como tales.
"""

import datetime as dt
from pathlib import Path

import openpyxl

from .base import ConversionError, ConversionResult
from .markdown import escape_cell, escape_inline, table_to_markdown


def convert_xlsx(path: Path) -> ConversionResult:
    try:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:
        raise ConversionError("No se pudo abrir el libro de Excel. Puede estar dañado.") from exc

    sections = []
    try:
        for sheet in workbook.worksheets:
            title = f"## Hoja: {escape_inline(sheet.title)}"
            if sheet.sheet_state != "visible":
                title += " (oculta)"
            rows = _sheet_rows(sheet)
            body = table_to_markdown(rows) if rows else "_Hoja vacía._"
            sections.append(f"{title}\n\n{body}")
    finally:
        workbook.close()

    if not sections:
        raise ConversionError("El libro de Excel no contiene hojas de cálculo.")
    return ConversionResult(markdown="\n\n".join(sections))


def _sheet_rows(sheet) -> list[list[str]]:
    rows = [[_format_cell(cell) for cell in row] for row in sheet.iter_rows()]
    rows = [r for r in rows if any(r)]
    if not rows:
        return []
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    keep = [c for c in range(width) if any(r[c] for r in rows)]
    return [[r[c] for c in keep] for r in rows]


def _format_cell(cell) -> str:
    value = getattr(cell, "value", None)
    if value is None:
        return ""
    number_format = getattr(cell, "number_format", "") or ""
    if isinstance(value, bool):
        text = "Sí" if value else "No"
    elif isinstance(value, dt.datetime):
        text = (
            value.date().isoformat()
            if value.time() == dt.time()
            else value.isoformat(" ", "minutes")
        )
    elif isinstance(value, dt.date):
        text = value.isoformat()
    elif isinstance(value, dt.time):
        text = value.isoformat("seconds")
    elif isinstance(value, int | float):
        text = _format_number(value, number_format)
    else:
        text = str(value)
    return escape_cell(text)


def _format_number(value: float, number_format: str) -> str:
    if "%" in number_format:
        return f"{value * 100:.10g}%"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, float):
        return f"{value:.15g}"
    return str(value)
