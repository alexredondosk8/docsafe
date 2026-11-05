"""División de un Markdown en fragmentos para enviarlos al modelo de lenguaje.

Cada fragmento es un trozo exacto del texto original (``text[start:end]``), de modo que las
posiciones encontradas en un fragmento se traducen al documento sumando ``start``.
Se respetan los bloques: párrafos y tablas (líneas seguidas sin línea en blanco) no se
cortan, salvo que un bloque solo supere el tamaño máximo; en ese caso se corta por líneas
y, si una línea es enorme, por espacios.
"""

import re
from dataclasses import dataclass

_BLOCK_SEPARATOR = re.compile(r"\n{2,}")


@dataclass(frozen=True)
class Chunk:
    start: int
    text: str

    @property
    def end(self) -> int:
        return self.start + len(self.text)


def _blocks(text: str) -> list[tuple[int, int]]:
    """Bloques separados por líneas en blanco (los separadores quedan dentro del bloque previo)."""
    bounds, start = [], 0
    for match in _BLOCK_SEPARATOR.finditer(text):
        bounds.append((start, match.end()))
        start = match.end()
    if start < len(text):
        bounds.append((start, len(text)))
    return bounds


def _split_long(text: str, start: int, end: int, max_chars: int) -> list[tuple[int, int]]:
    """Corta un bloque demasiado grande por líneas y, si hace falta, por espacios."""
    pieces, pos = [], start
    while end - pos > max_chars:
        window = text[pos : pos + max_chars]
        cut = window.rfind("\n")
        if cut <= 0:
            cut = window.rfind(" ")
        if cut <= 0:
            cut = max_chars - 1  # sin espacios: corte duro
        pieces.append((pos, pos + cut + 1))
        pos += cut + 1
    if pos < end:
        pieces.append((pos, end))
    return pieces


def split_into_chunks(text: str, max_chars: int = 2500) -> list[Chunk]:
    if max_chars < 100:
        raise ValueError("max_chars debe ser al menos 100")
    units: list[tuple[int, int]] = []
    for start, end in _blocks(text):
        if end - start > max_chars:
            units.extend(_split_long(text, start, end, max_chars))
        else:
            units.append((start, end))

    chunks: list[Chunk] = []
    current_start = current_end = None
    for start, end in units:
        if current_start is None:
            current_start, current_end = start, end
        elif end - current_start <= max_chars:
            current_end = end
        else:
            chunks.append(Chunk(current_start, text[current_start:current_end]))
            current_start, current_end = start, end
    if current_start is not None:
        chunks.append(Chunk(current_start, text[current_start:current_end]))
    return [c for c in chunks if c.text.strip()]
