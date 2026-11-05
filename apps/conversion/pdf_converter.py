"""PDF → Markdown con pymupdf4llm (modo de análisis de diseño, sin OCR).

Solo PDF con capa de texto. Los PDF escaneados (sin texto) se rechazan; las páginas sin
texto dentro de un PDF mixto se omiten con un aviso. Las imágenes se ignoran.
"""

import logging
import re
from pathlib import Path

import pymupdf
import pymupdf4llm

from .base import ConversionError, ConversionResult

logger = logging.getLogger(__name__)

# Una página con menos caracteres de texto que esto se considera "sin texto" (escaneada).
MIN_TEXT_CHARS_PER_PAGE = 10

_BOLD_HEADING = re.compile(r"^(#{1,6})\s+\*\*(.+?)\*\*\s*$", re.MULTILINE)
_PICTURE_PLACEHOLDER = re.compile(r"^.*(intentionally omitted|picture \[).*$", re.MULTILINE)

if hasattr(pymupdf4llm, "use_layout"):
    pymupdf4llm.use_layout(True)


def convert_pdf(path: Path) -> ConversionResult:
    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        raise ConversionError("No se pudo abrir el PDF. Puede estar dañado.") from exc

    with doc:
        if doc.needs_pass or doc.is_encrypted:
            raise ConversionError(
                "El PDF está protegido con contraseña. Quita la protección y vuelve a subirlo."
            )
        if doc.page_count == 0:
            raise ConversionError("El PDF no tiene páginas.")

        text_pages = [
            i
            for i, page in enumerate(doc)
            if len(page.get_text("text").strip()) >= MIN_TEXT_CHARS_PER_PAGE
        ]
        if not text_pages:
            raise ConversionError(
                "El PDF no contiene texto seleccionable (parece escaneado). "
                "Los PDF escaneados no se admiten en esta versión."
            )

        warnings = []
        skipped = doc.page_count - len(text_pages)
        if skipped:
            warnings.append(
                f"Se omitieron {skipped} de {doc.page_count} páginas sin texto "
                "(posiblemente escaneadas)."
            )

        try:
            markdown = pymupdf4llm.to_markdown(
                doc,
                pages=text_pages,
                use_ocr=False,
                force_ocr=False,
                write_images=False,
                embed_images=False,
                ignore_images=True,
                show_progress=False,
            )
        except Exception as exc:
            logger.exception("Fallo interno al convertir un PDF")
            raise ConversionError("No se pudo extraer el contenido del PDF.") from exc

    markdown = _BOLD_HEADING.sub(r"\1 \2", markdown)
    markdown = _PICTURE_PLACEHOLDER.sub("", markdown)
    return ConversionResult(markdown=markdown, warnings=warnings)
