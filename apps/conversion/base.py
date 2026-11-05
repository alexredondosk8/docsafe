"""Tipos comunes de la conversión a Markdown."""

from dataclasses import dataclass, field


class ConversionError(Exception):
    """No se pudo convertir el documento. El mensaje se muestra al usuario tal cual.

    Regla: el mensaje nunca debe incluir contenido del documento.
    """


@dataclass
class ConversionResult:
    markdown: str
    # Avisos para el usuario (p. ej. páginas omitidas). Sin contenido del documento.
    warnings: list[str] = field(default_factory=list)
