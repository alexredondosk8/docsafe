"""Conversión determinista (sin LLM) de documentos a Markdown.

Python puro: no depende de Django. Punto de entrada: ``convert(path, file_type)``.
"""

from pathlib import Path

from .base import ConversionError, ConversionResult
from .markdown import normalize

__all__ = ["ConversionError", "ConversionResult", "convert"]


def convert(path: Path | str, file_type: str) -> ConversionResult:
    """Convierte el archivo a Markdown. ``file_type``: 'pdf', 'docx' o 'xlsx'.

    Lanza ``ConversionError`` con un mensaje en español si no se puede convertir.
    """
    path = Path(path)
    # Importaciones diferidas: pymupdf carga un modelo de diseño que solo hace falta para PDF.
    if file_type == "pdf":
        from .pdf_converter import convert_pdf as converter
    elif file_type == "docx":
        from .docx_converter import convert_docx as converter
    elif file_type == "xlsx":
        from .xlsx_converter import convert_xlsx as converter
    else:
        raise ConversionError(f"Tipo de archivo no soportado: {file_type}")

    result = converter(path)
    result.markdown = normalize(result.markdown)
    if not result.markdown:
        raise ConversionError("El documento no contiene texto para convertir.")
    return result
