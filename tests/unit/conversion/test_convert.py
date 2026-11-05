"""Pruebas del punto de entrada de conversión y de la herramienta de terminal."""

import pytest

from apps.conversion import ConversionError, convert
from apps.conversion.__main__ import main


def test_tipo_no_soportado(fixture_path):
    with pytest.raises(ConversionError, match="no soportado"):
        convert(fixture_path("contrato.docx"), "doc")


@pytest.mark.parametrize(
    ("name", "file_type"),
    [("contrato.docx", "docx"), ("empleados.xlsx", "xlsx"), ("contrato.pdf", "pdf")],
)
def test_resultado_normalizado(fixture_path, name, file_type):
    md = convert(fixture_path(name), file_type).markdown
    assert md.endswith("\n") and not md.endswith("\n\n")
    assert "\r" not in md
    assert "\n\n\n" not in md


def test_cli_guarda_archivo(fixture_path, tmp_path):
    out = tmp_path / "salida.md"
    assert main([str(fixture_path("contrato.docx")), "-o", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("Soluciones Andinas")


def test_cli_archivo_inexistente(tmp_path, capsys):
    assert main([str(tmp_path / "no.pdf")]) == 2
    assert "No existe" in capsys.readouterr().err


def test_cli_error_de_conversion(fixture_path, capsys):
    assert main([str(fixture_path("escaneado.pdf"))]) == 1
    assert "escaneado" in capsys.readouterr().err
