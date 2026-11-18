"""OCR (reconocimiento de texto en imágenes) para PDF escaneados, con RapidOCR.

- Motor: RapidOCR 3 sobre onnxruntime, 100 % local en CPU. Detección y orientación usan los
  modelos incluidos en el paquete; el reconocimiento usa el modelo **latino** PP-OCRv5 (español
  con tildes y ñ), que se descarga UNA vez a ``models_dir`` y se verifica con SHA256.
  Después todo funciona sin internet: RapidOCR recibe la ruta local y no descarga nada.
- Se integra con pymupdf4llm como ``ocr_function``: la librería decide qué páginas lo necesitan,
  el texto reconocido se inserta en la página y el análisis de diseño (títulos, párrafos,
  tablas) funciona igual que con un PDF con texto.
- Lleva estadísticas por página (líneas y confianza media) para avisar de escaneos dudosos.

Python puro: no depende de Django. Nunca registra texto reconocido.
"""

import hashlib
import logging
import tempfile
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

MODEL_FILENAME = "latin_PP-OCRv5_rec_mobile.onnx"
MODEL_URL = (
    "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv5/rec/"
    + MODEL_FILENAME
)
MODEL_SHA256 = "b20bd37c168a570f583afbc8cd7925603890efbcdc000a59e22c269d160b5f5a"

PREPARE_COMMAND = "uv run python manage.py preparar_ocr"

ProgressCallback = Callable[[int, int], None]  # (páginas hechas, total estimado)


class OcrUnavailable(Exception):
    """El OCR no se puede usar. El mensaje está en español y se puede mostrar al usuario."""


@dataclass(frozen=True)
class OcrOptions:
    enabled: bool = True
    models_dir: Path | None = None
    # Resolución a la que se renderiza cada página para reconocerla (más = mejor y más lento).
    dpi: int = 300
    # Máximo de páginas escaneadas por documento (cada una tarda varios segundos).
    max_pages: int = 200
    # Confianza media por debajo de la cual una página se señala como dudosa (0-1).
    min_confidence: float = 0.80


# --- Modelo ----------------------------------------------------------------------------


def model_path(models_dir: Path) -> Path:
    return Path(models_dir) / MODEL_FILENAME


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


_VERIFIED: set[tuple[str, float, int]] = set()


def model_ready(models_dir: Path | None) -> bool:
    """True si el modelo está descargado y su SHA256 es el esperado."""
    if models_dir is None:
        return False
    path = model_path(models_dir)
    if not path.is_file():
        return False
    stat = path.stat()
    key = (str(path), stat.st_mtime, stat.st_size)
    if key not in _VERIFIED:
        if _sha256(path) != MODEL_SHA256:
            return False
        _VERIFIED.add(key)
    return True


def download_model(models_dir: Path, timeout: float = 120, url: str = MODEL_URL) -> Path:
    """Descarga el modelo latino (solo pesos del modelo, ningún documento) y lo verifica."""
    models_dir = Path(models_dir)
    models_dir.mkdir(parents=True, exist_ok=True)
    target = model_path(models_dir)
    if model_ready(models_dir):
        return target
    fd, tmp_name = tempfile.mkstemp(dir=models_dir, suffix=".part")
    tmp = Path(tmp_name)
    try:
        with open(fd, "wb") as out, urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
            while block := response.read(1024 * 1024):
                out.write(block)
        if _sha256(tmp) != MODEL_SHA256:
            raise OcrUnavailable(
                "El modelo de OCR descargado no pasó la verificación de integridad (SHA256)."
            )
        tmp.replace(target)
    except OcrUnavailable:
        raise
    except OSError as exc:
        raise OcrUnavailable(
            "No se pudo descargar el modelo de OCR (se necesita internet solo esta vez). "
            f"Detalle: {type(exc).__name__}."
        ) from exc
    finally:
        tmp.unlink(missing_ok=True)
    return target


# --- Motor -----------------------------------------------------------------------------


@dataclass
class PageStats:
    lines: int = 0
    confidence_sum: float = 0.0

    @property
    def confidence(self) -> float:
        return self.confidence_sum / self.lines if self.lines else 0.0


@dataclass
class OcrRun:
    """Resultado acumulado del OCR de un documento (sin texto: solo cifras)."""

    pages: dict[int, PageStats] = field(default_factory=dict)

    def low_confidence_pages(self, threshold: float) -> list[int]:
        """Números de página (desde 1) con texto reconocido pero confianza baja."""
        return sorted(n + 1 for n, s in self.pages.items() if s.lines and s.confidence < threshold)

    def read_pages(self) -> int:
        """Páginas en las que el OCR encontró texto."""
        return sum(1 for s in self.pages.values() if s.lines)


class OcrEngine:
    """Envuelve RapidOCR. Cargarlo tarda ~1-2 s, por eso se reutiliza (``get_engine``)."""

    def __init__(self, models_dir: Path, dpi: int = 300) -> None:
        if not model_ready(models_dir):
            raise OcrUnavailable(
                f"El modelo de OCR no está descargado. Ejecuta una vez: {PREPARE_COMMAND}"
            )
        try:
            from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR
        except ImportError as exc:  # pragma: no cover - dependencia del proyecto
            raise OcrUnavailable("RapidOCR no está instalado (uv sync).") from exc

        logging.getLogger("RapidOCR").setLevel(logging.CRITICAL)
        self.dpi = dpi
        self._rapid = RapidOCR(
            params={
                "Global.log_level": "critical",
                "Rec.lang_type": LangRec.LATIN,
                "Rec.ocr_version": OCRVersion.PPOCRV5,
                "Rec.model_type": ModelType.MOBILE,
                # Ruta local: RapidOCR no intenta descargar nada.
                "Rec.model_path": str(model_path(models_dir)),
            }
        )

    def recognize(self, image) -> list[tuple]:
        """Detecta y reconoce texto en una imagen (array numpy): [(caja, texto, confianza)]."""
        result = self._rapid(image)
        if result.boxes is None or result.txts is None or result.scores is None:
            return []
        return list(zip(result.boxes, result.txts, result.scores, strict=False))

    def ocr_function(self, run: OcrRun, on_page: Callable[[], None] | None = None):
        """Función para ``pymupdf4llm.to_markdown(ocr_function=...)``."""
        from pymupdf4llm.ocr.exec_ocr_interface import exec_ocr_full

        def _ocr_page(page, dpi=None, language=None, keep_ocr_text=False):
            stats = run.pages.setdefault(page.number, PageStats())

            def _recognize(image):
                lines = self.recognize(image)
                stats.lines += len(lines)
                stats.confidence_sum += sum(float(line[2]) for line in lines)
                return lines

            exec_ocr_full(
                page, _recognize, dpi=self.dpi, language=language, keep_ocr_text=keep_ocr_text
            )
            if on_page:
                on_page()

        return _ocr_page


_ENGINES: dict[tuple[str, int], OcrEngine] = {}


def get_engine(models_dir: Path, dpi: int = 300) -> OcrEngine:
    key = (str(Path(models_dir).resolve()), dpi)
    if key not in _ENGINES:
        _ENGINES[key] = OcrEngine(models_dir, dpi)
    return _ENGINES[key]
