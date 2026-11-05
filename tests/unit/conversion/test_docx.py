"""Pruebas de la conversión Word (.docx) → Markdown."""

import pytest
from docx import Document

from apps.conversion import ConversionError, convert
from tests.fixtures.generate import _add_hyperlink


@pytest.fixture(scope="module")
def contrato_md():
    from tests.unit.conversion.conftest import FIXTURES

    return convert(FIXTURES / "contrato.docx", "docx").markdown


def test_encabezado_al_inicio_y_pie_al_final(contrato_md):
    parts = contrato_md.split("\n---\n")
    assert len(parts) == 3
    assert "NIT 900.123.456-7" in parts[0]
    assert "# Contrato" in parts[1]
    assert parts[2].strip() == "Documento confidencial"


def test_titulos(contrato_md):
    assert "# Contrato de prestación de servicios No. CPS-2024-0153\n" in contrato_md
    assert "\n## Cláusulas\n" in contrato_md


def test_negrita_y_cursiva(contrato_md):
    assert "**PRIMERA. Objeto:** prestar servicios de *consultoría* en" in contrato_md


def test_listas_con_vinetas_y_numeradas_separadas(contrato_md):
    assert (
        "- Entregar informes mensuales.\n- Asistir a reuniones de seguimiento.\n\n" in contrato_md
    )
    assert "1. Firma del acta de inicio.\n1. Ejecución del servicio." in contrato_md


def test_tabla_con_cabecera_pipe_escapado_y_celdas_combinadas(contrato_md):
    assert "| Concepto | Valor | Observación |\n|---|---|---|" in contrato_md
    assert "| Honorarios | $ 5.000.000 | Mensual \\| IVA incluido |" in contrato_md
    assert "| Total | $ 5.800.000 |  |" in contrato_md


def test_enlace_mailto_se_muestra_como_texto(contrato_md):
    assert "Contacto: juan.perez@ejemplo.com" in contrato_md
    assert "mailto:" not in contrato_md


def test_escapa_caracteres_de_markdown(contrato_md):
    assert "\\*Texto con asteriscos\\* y # almohadilla" in contrato_md


def test_salto_de_linea_dentro_de_parrafo(contrato_md):
    assert "Línea uno\nLínea dos" in contrato_md


def test_no_pierde_datos_del_documento(contrato_md):
    """Todo dato del original debe llegar al Markdown para que luego se anonimice."""
    for value in [
        "Soluciones Andinas S.A.S.",
        "900.123.456-7",
        "María Fernanda López Ruiz",
        "52.345.678",
        "Juan Carlos Pérez Gómez",
        "1.020.304.050",
        "15/03/1985",
        "39 años",
        "juan.perez@ejemplo.com",
        "+57 310 555 1234",
        "Calle 45 # 12-34, Bogotá",
        "CPS-2024-0153",
    ]:
        assert value in contrato_md, value


# --- Documentos construidos en la prueba -------------------------------------------------


def _save(doc, tmp_path):
    path = tmp_path / "doc.docx"
    doc.save(path)
    return path


def test_enlace_web_en_formato_markdown(tmp_path):
    doc = Document()
    p = doc.add_paragraph("Ver ")
    _add_hyperlink(p, "https://ejemplo.com/politica", "la política")
    md = convert(_save(doc, tmp_path), "docx").markdown
    assert "Ver [la política](https://ejemplo.com/politica)" in md


def test_lista_anidada(tmp_path):
    doc = Document()
    doc.add_paragraph("Nivel 1", style="List Bullet")
    p = doc.add_paragraph("Nivel 2", style="List Bullet")
    num_pr = p._p.get_or_add_pPr().get_or_add_numPr()
    num_pr.get_or_add_ilvl().val = 1
    num_pr.get_or_add_numId().val = doc.styles["List Bullet"].element.pPr.numPr.numId.val
    md = convert(_save(doc, tmp_path), "docx").markdown
    assert "- Nivel 1\n  - Nivel 2" in md


def test_tabla_vacia_se_omite(tmp_path):
    doc = Document()
    doc.add_paragraph("Antes")
    doc.add_table(rows=2, cols=2)
    md = convert(_save(doc, tmp_path), "docx").markdown
    assert "|" not in md


def test_documento_sin_texto_da_error(tmp_path):
    doc = Document()
    doc.add_paragraph("")
    with pytest.raises(ConversionError, match="no contiene texto"):
        convert(_save(doc, tmp_path), "docx")


def test_archivo_danado_da_error(tmp_path):
    path = tmp_path / "roto.docx"
    path.write_bytes(b"PK\x03\x04 esto no es un docx")
    with pytest.raises(ConversionError, match="No se pudo abrir"):
        convert(path, "docx")
