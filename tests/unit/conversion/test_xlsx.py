"""Pruebas de la conversión Excel (.xlsx) → Markdown."""

import datetime as dt

import openpyxl
import pytest

from apps.conversion import ConversionError, convert


@pytest.fixture(scope="module")
def empleados_md():
    from tests.unit.conversion.conftest import FIXTURES

    return convert(FIXTURES / "empleados.xlsx", "xlsx").markdown


def test_una_seccion_por_hoja_en_orden(empleados_md):
    titles = [line for line in empleados_md.splitlines() if line.startswith("## ")]
    assert titles == [
        "## Hoja: Empleados",
        "## Hoja: Resumen",
        "## Hoja: Vacía",
        "## Hoja: Oculta (oculta)",
    ]


def test_cabecera_y_formato_de_valores(empleados_md):
    assert "| Nombre | Cédula | Correo | Fecha de nacimiento | Salario | Bono |" in empleados_md
    fila = (
        "| Juan Carlos Pérez Gómez | 1.020.304.050 | juan.perez@ejemplo.com "
        "| 1985-03-15 | 5000000 |"
    )
    assert fila in empleados_md
    assert "| 7250000.5 | 0.1 |" in empleados_md


def test_escapa_pipe_y_saltos_de_linea(empleados_md):
    assert "| Pedro \\| Ramírez |" in empleados_md
    assert "| Nota:<br>fila con salto de línea |" in empleados_md


def test_omite_filas_vacias(empleados_md):
    assert "|  |  |  |  |  |  |" not in empleados_md


def test_hoja_vacia(empleados_md):
    assert "## Hoja: Vacía\n\n_Hoja vacía._" in empleados_md


def test_hoja_oculta_se_incluye(empleados_md):
    assert "| Teléfono | +57 310 555 1234 |" in empleados_md


def _book(tmp_path, fill):
    wb = openpyxl.Workbook()
    fill(wb.active)
    path = tmp_path / "libro.xlsx"
    wb.save(path)
    return convert(path, "xlsx").markdown


def test_booleanos_porcentajes_y_fecha_hora(tmp_path):
    def fill(ws):
        ws.append(["Activo", "Avance", "Registro", "Hora"])
        ws.append([True, 0.255, dt.datetime(2024, 5, 1, 14, 30), dt.time(8, 15)])
        ws["B2"].number_format = "0.0%"

    md = _book(tmp_path, fill)
    assert "| Sí | 25.5% | 2024-05-01 14:30 | 08:15:00 |" in md


def test_omite_columnas_vacias_al_inicio(tmp_path):
    def fill(ws):
        ws["C3"] = "Título"
        ws["D3"] = "Valor"
        ws["C4"] = "a"
        ws["D4"] = 1

    md = _book(tmp_path, fill)
    assert "| Título | Valor |\n|---|---|\n| a | 1 |" in md


def test_archivo_danado_da_error(tmp_path):
    path = tmp_path / "roto.xlsx"
    path.write_bytes(b"PK\x03\x04 no es un xlsx")
    with pytest.raises(ConversionError, match="No se pudo abrir el libro"):
        convert(path, "xlsx")
