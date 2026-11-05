"""Utilidades para producir Markdown limpio y consistente."""

import re
import unicodedata
from collections.abc import Sequence

_BLOCK_START = re.compile(r"^(\s*)(#{1,6}\s|>|[-+*]\s|\d+[.)]\s)")
_MANY_BLANK_LINES = re.compile(r"\n{3,}")
_TRAILING_SPACES = re.compile(r"[ \t]+$", re.MULTILINE)
_HEADING_WITHOUT_BLANK = re.compile(r"^(#{1,6} .+)\n(?=\S)", re.MULTILINE)


def escape_inline(text: str) -> str:
    """Escapa los caracteres que Markdown interpretaría como formato dentro de una línea."""
    return text.replace("\\", "\\\\").replace("*", "\\*").replace("`", "\\`")


def escape_block_start(text: str) -> str:
    """Evita que un párrafo que empieza por '#', '-', '1.' o '>' se lea como bloque."""
    return _BLOCK_START.sub(lambda m: m.group(1) + "\\" + m.group(2), text, count=1)


def escape_cell(text: str) -> str:
    """Prepara el texto de una celda: escapa '|' y convierte saltos de línea en <br>."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    text = text.replace("|", "\\|")
    return "<br>".join(part.strip() for part in text.split("\n"))


def table_to_markdown(rows: Sequence[Sequence[str]]) -> str:
    """Convierte filas (la primera es la cabecera) en una tabla Markdown.

    Las celdas ya deben venir escapadas con ``escape_cell``. Rellena filas cortas.
    """
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    if width == 0:
        return ""
    padded = [list(r) + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(padded[0]) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in padded[1:]]
    return "\n".join(lines)


def normalize(markdown: str) -> str:
    """Normalización final común a todos los formatos.

    - NFKC: convierte ligaduras tipográficas ("ﬁ" → "fi"), espacios duros y similares en
      caracteres normales, para que la anonimización por regex funcione igual en todos los formatos.
    - Saltos de línea Unix, sin espacios al final de línea, máximo una línea en blanco seguida.
    """
    text = unicodedata.normalize("NFKC", markdown)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _TRAILING_SPACES.sub("", text)
    text = _HEADING_WITHOUT_BLANK.sub(r"\1\n\n", text)
    text = _MANY_BLANK_LINES.sub("\n\n", text)
    return text.strip() + "\n" if text.strip() else ""
