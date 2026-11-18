"""Pruebas del OCR para PDF escaneados (Fase 8).

- Con OCR simulado (siempre se ejecutan): modelo, descarga, avisos, límites, desactivado.
- Con el OCR real (RapidOCR + modelo latino en var/modelos_ocr): se omiten si el modelo no
  está descargado (`uv run python manage.py preparar_ocr`).
"""

import hashlib
import io
from pathlib import Path

import pytest

from apps.anonymization import Anonymizer
from apps.conversion import ConversionError, OcrOptions, convert, pdf_converter
from apps.conversion import ocr as ocr_module
from apps.conversion.ocr import OcrEngine, OcrUnavailable, download_model, model_ready

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
REAL_MODELS = Path(__file__).resolve().parents[3] / "var" / "modelos_ocr"

needs_real_ocr = pytest.mark.skipif(
    not model_ready(REAL_MODELS),
    reason="modelo de OCR no descargado (uv run python manage.py preparar_ocr)",
)


# --- Modelo: verificación y descarga ---------------------------------------------------


def test_modelo_ausente_no_esta_listo(tmp_path):
    assert not model_ready(tmp_path)
    assert not model_ready(None)


def test_modelo_alterado_no_esta_listo(tmp_path):
    (tmp_path / ocr_module.MODEL_FILENAME).write_bytes(b"modelo manipulado")
    assert not model_ready(tmp_path)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_descarga_y_verifica(tmp_path, monkeypatch):
    data = b"pesos del modelo" * 1000
    monkeypatch.setattr(ocr_module, "MODEL_SHA256", hashlib.sha256(data).hexdigest())
    monkeypatch.setattr(
        ocr_module.urllib.request, "urlopen", lambda url, timeout: FakeResponse(data)
    )

    path = download_model(tmp_path)

    assert path.read_bytes() == data
    assert model_ready(tmp_path)
    assert list(tmp_path.glob("*.part")) == []  # sin restos de la descarga


def test_descarga_con_hash_incorrecto_se_descarta(tmp_path, monkeypatch):
    tmp_path = tmp_path / "modelos"  # carpeta propia (tmp_path ya tiene "uploads")
    monkeypatch.setattr(
        ocr_module.urllib.request, "urlopen", lambda url, timeout: FakeResponse(b"otra cosa")
    )
    with pytest.raises(OcrUnavailable, match="verificación de integridad"):
        download_model(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_descarga_sin_internet(tmp_path):
    # tests/conftest.py bloquea urlopen en todas las pruebas
    with pytest.raises(OcrUnavailable, match="se necesita internet solo esta vez"):
        download_model(tmp_path)


def test_motor_sin_modelo_explica_como_prepararlo(tmp_path):
    with pytest.raises(OcrUnavailable, match="preparar_ocr"):
        OcrEngine(tmp_path)


# --- Conversión con OCR simulado -------------------------------------------------------


class FakeEngine(OcrEngine):
    """Usa la integración real con pymupdf4llm, pero «reconoce» un texto fijo."""

    def __init__(self, text="Texto reconocido por OCR", score=0.95):
        self.dpi = 150
        self.text, self.score = text, score

    def recognize(self, image):
        if not self.text:
            return []
        height, width = image.shape[:2]
        box = [[40, 40], [width - 40, 40], [width - 40, 90], [40, 90]]
        return [(box, self.text, self.score)]


@pytest.fixture
def fake_engine(monkeypatch):
    engine = FakeEngine()
    monkeypatch.setattr(pdf_converter, "get_engine", lambda models_dir, dpi: engine)
    return engine


OPTIONS = OcrOptions(models_dir=Path("no-importa"))


def test_pdf_escaneado_se_lee_con_ocr(fake_engine):
    result = convert(FIXTURES / "contrato_escaneado.pdf", "pdf", ocr=OPTIONS)
    assert "Texto reconocido por OCR" in result.markdown
    assert result.ocr_pages == 2
    assert result.warnings[0].startswith("Se reconoció texto con OCR en 2 de 2 páginas")


def test_pdf_mixto_solo_ocr_en_paginas_escaneadas(fake_engine):
    result = convert(FIXTURES / "mixto_ocr.pdf", "pdf", ocr=OPTIONS)
    assert "Juan Carlos Pérez Gómez" in result.markdown  # página 1: texto real
    assert "Texto reconocido por OCR" in result.markdown  # página 2: OCR
    assert result.ocr_pages == 1


def test_pagina_escaneada_sin_texto_se_avisa(fake_engine):
    """La librería no lee una página con solo un recuadro gris; aun así se avisa."""
    result = convert(FIXTURES / "mixto.pdf", "pdf", ocr=OPTIONS)
    assert "Página con texto del contrato." in result.markdown
    assert result.ocr_pages == 0
    assert any(
        "No se encontró texto en la(s) página(s) escaneada(s) 2" in w for w in result.warnings
    )


def test_progreso_por_pagina(fake_engine):
    calls = []
    convert(
        FIXTURES / "contrato_escaneado.pdf",
        "pdf",
        ocr=OPTIONS,
        on_progress=lambda d, t: calls.append((d, t)),
    )
    assert calls == [(0, 2), (1, 2), (2, 2)]


def test_aviso_de_confianza_baja(fake_engine):
    fake_engine.score = 0.42
    result = convert(FIXTURES / "contrato_escaneado.pdf", "pdf", ocr=OPTIONS)
    assert any(
        "Calidad de reconocimiento baja en la(s) página(s) 1, 2" in w for w in result.warnings
    )


def test_sin_texto_reconocible_da_error(fake_engine):
    fake_engine.text = ""
    with pytest.raises(ConversionError, match="No se reconoció texto en el PDF"):
        convert(FIXTURES / "contrato_escaneado.pdf", "pdf", ocr=OPTIONS)


def test_limite_de_paginas_escaneadas(fake_engine):
    with pytest.raises(ConversionError, match="máximo es 0"):
        convert(
            FIXTURES / "escaneado.pdf", "pdf", ocr=OcrOptions(models_dir=Path("x"), max_pages=0)
        )


def test_pdf_con_texto_no_usa_ocr(monkeypatch):
    monkeypatch.setattr(pdf_converter, "get_engine", lambda *a: pytest.fail("no debe cargar OCR"))
    result = convert(FIXTURES / "contrato.pdf", "pdf", ocr=OPTIONS)
    assert result.ocr_pages == 0


def test_ocr_desactivado():
    with pytest.raises(ConversionError, match="OCR\\) está desactivado"):
        convert(FIXTURES / "escaneado.pdf", "pdf", ocr=OcrOptions(enabled=False))


def test_modelo_no_descargado_explica_como_prepararlo(tmp_path):
    with pytest.raises(ConversionError, match="preparar_ocr"):
        convert(FIXTURES / "escaneado.pdf", "pdf", ocr=OcrOptions(models_dir=tmp_path))


def test_mixto_sin_modelo_omite_paginas_y_avisa(tmp_path):
    result = convert(FIXTURES / "mixto.pdf", "pdf", ocr=OcrOptions(models_dir=tmp_path))
    assert "Página con texto del contrato." in result.markdown
    assert result.warnings[0].startswith(
        "Se omitieron 1 de 2 páginas escaneadas porque el modelo de OCR no está descargado"
    )


# --- OCR real ---------------------------------------------------------------------------

REAL = OcrOptions(models_dir=REAL_MODELS)


@needs_real_ocr
def test_ocr_real_contrato_escaneado_con_tildes_y_estructura():
    result = convert(FIXTURES / "contrato_escaneado.pdf", "pdf", ocr=REAL)
    md = result.markdown
    assert result.ocr_pages == 2
    assert md.startswith("# Contrato de prestación de servicios")
    for text in [
        "María Fernanda López Ruiz",
        "Juan Carlos Pérez Gómez",
        "52.345.678",
        "juan.perez@ejemplo.com",
        "## Cláusulas",
        "consultoría",
        "(39 años)",
    ]:
        assert text in md, text
    assert "|Juan Pérez|" in md.replace(" | ", "|")  # tabla del anexo


@needs_real_ocr
def test_ocr_real_sin_fugas_tras_anonimizar():
    md = convert(FIXTURES / "contrato_escaneado.pdf", "pdf", ocr=REAL).markdown
    out = Anonymizer().anonymize(md)
    leaked = [
        v
        for v in [
            "Soluciones Andinas",
            "900.123.456",
            "María Fernanda",
            "52.345.678",
            "Juan Carlos",
            "1.020.304.050",
            "15/03/1985",
            "39 años",
            "juan.perez@ejemplo.com",
            "310 555 1234",
            "Calle 45",
            "CPS-2024-0153",
            "Juan Pérez",
            "María López",
        ]
        if v in out
    ]
    assert leaked == []


@needs_real_ocr
def test_ocr_real_pdf_mixto():
    result = convert(FIXTURES / "mixto_ocr.pdf", "pdf", ocr=REAL)
    assert result.ocr_pages == 1
    assert "Juan Carlos Pérez Gómez" in result.markdown  # página 1, con texto
    assert "María López" in result.markdown  # página 2, por OCR


@needs_real_ocr
def test_ocr_real_pagina_sin_texto():
    with pytest.raises(ConversionError, match="No se reconoció texto"):
        convert(FIXTURES / "escaneado.pdf", "pdf", ocr=REAL)


@needs_real_ocr
def test_ocr_real_no_usa_internet(monkeypatch):
    """Con el modelo local, cargar el motor no intenta ninguna conexión."""
    import socket

    def no_network(*args, **kwargs):
        raise AssertionError("intento de conexión de red")

    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(ocr_module, "_ENGINES", {})
    engine = ocr_module.get_engine(REAL_MODELS)
    assert engine is not None
