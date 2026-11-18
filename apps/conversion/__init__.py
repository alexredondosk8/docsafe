"""Conversión determinista (sin LLM) de documentos a Markdown.

Python puro: no depende de Django. Punto de entrada: ``convert(path, file_type)``.
Los PDF escaneados se leen con OCR local si se pasan ``ocr=OcrOptions(...)``.
"""

from pathlib import Path

from .base import ConversionError, ConversionResult
from .markdown import normalize
from .ocr import OcrOptions, OcrUnavailable

__all__ = ["ConversionError", "ConversionResult", "OcrOptions", "OcrUnavailable", "convert"]


def convert(
    path: Path | str,
    file_type: str,
    ocr: OcrOptions | None = None,
    on_progress=None,
) -> ConversionResult:
    """Convierte el archivo a Markdown. ``file_type``: 'pdf', 'docx' o 'xlsx'.

    ``ocr``: opciones de reconocimiento de texto para PDF escaneados (sin ellas no se usa OCR).
    ``on_progress(hechas, total)``: avance del OCR por páginas.
    Lanza ``ConversionError`` con un mensaje en español si no se puede convertir.
    """
    path = Path(path)
    # Importaciones diferidas: pymupdf carga un modelo de diseño que solo hace falta para PDF.
    if file_type == "pdf":
        from .pdf_converter import convert_pdf

        result = convert_pdf(path, ocr=ocr, on_progress=on_progress)
    elif file_type == "docx":
        from .docx_converter import convert_docx

        result = convert_docx(path)
    elif file_type == "xlsx":
        from .xlsx_converter import convert_xlsx

        result = convert_xlsx(path)
    else:
        raise ConversionError(f"Tipo de archivo no soportado: {file_type}")

    result.markdown = normalize(result.markdown)
    if not result.markdown:
        raise ConversionError("El documento no contiene texto para convertir.")
    return result
