"""Pruebas de la conversión PDF → Markdown."""

import pytest

from apps.conversion import ConversionError, convert


@pytest.fixture(scope="module")
def contrato():
    from tests.unit.conversion.conftest import FIXTURES

    return convert(FIXTURES / "contrato.pdf", "pdf")


def test_titulos_sin_negrita_redundante(contrato):
    md = contrato.markdown
    assert md.startswith("# Contrato de prestación de servicios No. CPS-2024-0153\n\n")
    assert "## Cláusulas" in md
    assert "**Cláusulas**" not in md


def test_parrafo_unido_en_una_linea(contrato):
    """Las líneas del PDF se unen: un nombre no queda partido entre dos líneas."""
    line = next(line for line in contrato.markdown.splitlines() if line.startswith("Entre "))
    assert "Juan Carlos Pérez Gómez" in line
    assert line.endswith("se celebra el presente contrato.")


def test_tabla_con_bordes(contrato):
    assert "|Concepto|Valor|Responsable|" in contrato.markdown.replace(" | ", "|")
    assert "Juan Pérez" in contrato.markdown


def test_lista(contrato):
    assert "- Entregar informes mensuales." in contrato.markdown


def test_sin_avisos_ni_marcadores_de_imagen(contrato):
    assert contrato.warnings == []
    assert "picture" not in contrato.markdown.lower()


def test_no_pierde_datos(contrato):
    for value in [
        "Soluciones Andinas S.A.S.",
        "900.123.456-7",
        "52.345.678",
        "1.020.304.050",
        "juan.perez@ejemplo.com",
        "+57 310 555 1234",
        "identificada",  # sin ligadura "ﬁ"
    ]:
        assert value in contrato.markdown, value


def test_pdf_escaneado_da_error(fixture_path):
    with pytest.raises(ConversionError, match="parece escaneado"):
        convert(fixture_path("escaneado.pdf"), "pdf")


def test_pdf_protegido_da_error(fixture_path):
    with pytest.raises(ConversionError, match="protegido con contraseña"):
        convert(fixture_path("protegido.pdf"), "pdf")


def test_pdf_mixto_omite_paginas_sin_texto_con_aviso(fixture_path):
    result = convert(fixture_path("mixto.pdf"), "pdf")
    assert "Página con texto del contrato." in result.markdown
    assert result.warnings == ["Se omitieron 1 de 2 páginas sin texto (posiblemente escaneadas)."]


def test_pdf_danado_da_error(tmp_path):
    path = tmp_path / "roto.pdf"
    path.write_bytes(b"%PDF-1.7\nbasura sin estructura")
    with pytest.raises(ConversionError):
        convert(path, "pdf")
