"""PDF → Markdown con pymupdf4llm (modo de análisis de diseño).

- Páginas con texto: se extrae directamente (rápido y exacto).
- Páginas escaneadas (sin texto): se reconocen con OCR local (``ocr.py``, RapidOCR latino) y
  pasan por el mismo análisis de diseño, así que se conservan títulos, párrafos y tablas.
- Si el OCR está desactivado o no disponible, las páginas escaneadas se omiten con un aviso
  (o se rechaza el PDF si todas lo son).
Las imágenes se ignoran (no se incrustan en el Markdown).
"""

import logging
import re
from pathlib import Path

import pymupdf
import pymupdf4llm

from .base import ConversionError, ConversionResult
from .ocr import OcrOptions, OcrRun, OcrUnavailable, get_engine

logger = logging.getLogger(__name__)

# Una página con menos caracteres de texto que esto se considera "sin texto" (escaneada).
MIN_TEXT_CHARS_PER_PAGE = 10

_BOLD_HEADING = re.compile(r"^(#{1,6})\s+\*\*(.+?)\*\*\s*$", re.MULTILINE)
_PICTURE_PLACEHOLDER = re.compile(r"^.*(intentionally omitted|picture \[).*$", re.MULTILINE)

if hasattr(pymupdf4llm, "use_layout"):
    pymupdf4llm.use_layout(True)


def _as_clause(message: str) -> str:
    """Convierte un mensaje en una subordinada: 'El modelo… falta.' → 'el modelo… falta'."""
    message = message.strip().rstrip(".")
    return message[:1].lower() + message[1:]


def _pages_list(numbers: list[int]) -> str:
    shown = ", ".join(str(n) for n in numbers[:10])
    return shown + (f" y {len(numbers) - 10} más" if len(numbers) > 10 else "")


def convert_pdf(path: Path, ocr: OcrOptions | None = None, on_progress=None) -> ConversionResult:
    ocr = ocr or OcrOptions(enabled=False)
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
        scanned = doc.page_count - len(text_pages)

        engine, unavailable_reason = None, ""
        if scanned:
            if not ocr.enabled:
                unavailable_reason = (
                    "el reconocimiento de texto (OCR) está desactivado (DOCSAFE_USAR_OCR=False)"
                )
            elif scanned > ocr.max_pages:
                raise ConversionError(
                    f"El PDF tiene {scanned} páginas escaneadas y el máximo es {ocr.max_pages} "
                    "(DOCSAFE_OCR_MAX_PAGINAS). Divide el documento en partes más pequeñas."
                )
            else:
                try:
                    engine = get_engine(ocr.models_dir, ocr.dpi)
                except OcrUnavailable as exc:
                    unavailable_reason = str(exc)

        warnings: list[str] = []
        run = OcrRun()
        if engine is None:
            if not text_pages:
                raise ConversionError(
                    "El PDF no contiene texto seleccionable (parece escaneado) y no se pudo "
                    f"usar el reconocimiento de texto (OCR): {_as_clause(unavailable_reason)}."
                )
            pages, use_ocr, ocr_function = text_pages, False, None
            if scanned:
                warnings.append(
                    f"Se omitieron {scanned} de {doc.page_count} páginas escaneadas porque "
                    f"{_as_clause(unavailable_reason)}."
                )
        else:
            pages, use_ocr = list(range(doc.page_count)), True
            done = [0]

            def on_page():
                done[0] += 1
                if on_progress:
                    on_progress(min(done[0], scanned), scanned)

            if on_progress:
                on_progress(0, scanned)
            ocr_function = engine.ocr_function(run, on_page)

        try:
            markdown = pymupdf4llm.to_markdown(
                doc,
                pages=pages,
                use_ocr=use_ocr,
                force_ocr=False,
                ocr_function=ocr_function,
                write_images=False,
                embed_images=False,
                ignore_images=True,
                show_progress=False,
            )
        except Exception as exc:
            logger.exception("Fallo interno al convertir un PDF")
            raise ConversionError("No se pudo extraer el contenido del PDF.") from exc

    if engine is not None:
        scanned_pages = sorted(set(range(len(pages))) - set(text_pages))
        warnings.extend(_ocr_warnings(run, scanned_pages, doc_pages=len(pages), ocr=ocr))

    markdown = _BOLD_HEADING.sub(r"\1 \2", markdown)
    markdown = _PICTURE_PLACEHOLDER.sub("", markdown)
    if engine is not None and not markdown.strip():
        raise ConversionError(
            "No se reconoció texto en el PDF. Puede tener páginas en blanco, texto manuscrito "
            "o un escaneo de muy baja calidad."
        )
    return ConversionResult(markdown=markdown, warnings=warnings, ocr_pages=run.read_pages())


def _ocr_warnings(
    run: OcrRun, scanned_pages: list[int], doc_pages: int, ocr: OcrOptions
) -> list[str]:
    warnings = []
    read = run.read_pages()
    if read:
        warnings.append(
            f"Se reconoció texto con OCR en {read} de {doc_pages} páginas (escaneadas). "
            "El OCR puede confundir letras o números: revisa el resultado con atención."
        )
    low = run.low_confidence_pages(ocr.min_confidence)
    if low:
        warnings.append(
            f"Calidad de reconocimiento baja en la(s) página(s) {_pages_list(low)}: el escaneo "
            "puede estar borroso, torcido o con poco contraste. Revisa esas partes."
        )
    # Páginas escaneadas sin texto reconocido (la librería pudo decidir no leerlas: sin texto).
    empty = [n + 1 for n in scanned_pages if not run.pages.get(n) or not run.pages[n].lines]
    if empty:
        warnings.append(
            f"No se encontró texto en la(s) página(s) escaneada(s) {_pages_list(empty)} "
            "(¿en blanco, solo imágenes o manuscritas?)."
        )
    return warnings
