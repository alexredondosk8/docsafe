"""Pruebas de las reglas regex: casos que DEBEN detectarse y casos que NO.

Todos los datos son ficticios.
"""

import pytest

from apps.anonymization import Anonymizer, AnonymizerConfig, EntityType
from apps.anonymization.rules import single_line

T = EntityType


def detect(text: str, **config) -> list[tuple[EntityType, str]]:
    anonymizer = Anonymizer(AnonymizerConfig(**config))
    return [(s.type, text[s.start : s.end]) for s in anonymizer.find_spans(text)]


def assert_detects(text: str, entity_type: EntityType, value: str, **config) -> None:
    found = detect(text, **config)
    assert (entity_type, value) in found, f"esperado {entity_type}={value!r}; encontrado {found}"


def assert_no_type(text: str, entity_type: EntityType, **config) -> None:
    found = [f for f in detect(text, **config) if f[0] == entity_type]
    assert not found, f"no se esperaba {entity_type}; encontrado {found}"


# --- Correo -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("correo juan.perez@ejemplo.com.", "juan.perez@ejemplo.com"),
        ("Escribir a MARIA_lopez+1@empresa.com.co hoy", "MARIA_lopez+1@empresa.com.co"),
        ("<contacto@sub.dominio.org>", "contacto@sub.dominio.org"),
        ("| Correo | ana@x.co |", "ana@x.co"),
    ],
)
def test_correo(text, value):
    assert_detects(text, T.CORREO, value)


@pytest.mark.parametrize("text", ["usuario@", "síguenos en @docsafe", "texto@dominio sin tld"])
def test_no_es_correo(text):
    assert_no_type(text, T.CORREO)


# --- Teléfono ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("teléfono +57 310 555 1234,", "+57 310 555 1234"),
        ("cel 3105551234", "3105551234"),
        ("llamar al 310-555-1234", "310-555-1234"),
        ("fijo (601) 345 6789", "(601) 345 6789"),
        ("fijo 601 3456789", "601 3456789"),
        ("PBX +57 601 345 6789", "+57 601 345 6789"),
        ("oficina en EE. UU. +1 212 555 0198", "+1 212 555 0198"),
        ("Tel: 345 67 89", "345 67 89"),
        ("Celular: 300.123.4567", "300.123.4567"),
    ],
)
def test_telefono(text, value):
    assert_detects(text, T.TELEFONO, value)


@pytest.mark.parametrize(
    "text",
    ["Valor: $ 5.000.000", "Radicado 2024123456", "Año 2024", "Página 3 de 10", "C.C. 52.345.678"],
)
def test_no_es_telefono(text):
    assert_no_type(text, T.TELEFONO)


# --- Cédula y otros documentos ----------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("identificado con C.C. 1.020.304.050,", "1.020.304.050"),
        ("CC 52345678", "52345678"),
        ("cédula de ciudadanía No. 79.111.222", "79.111.222"),
        ("Cedula: 79111222", "79111222"),
        ("C.E. 123456 expedida", "123456"),
        ("T.I. 1.098.765.432", "1.098.765.432"),
        ("documento de identidad: 52 345 678", "52 345 678"),
        ("NUIP 1098765432", "1098765432"),
        ("número de identificación 80.123.456", "80.123.456"),
    ],
)
def test_cedula(text, value):
    assert_detects(text, T.CEDULA, value)


@pytest.mark.parametrize(
    "text",
    [
        "Honorarios $ 1.020.304.050",
        "ACCESO 12345",
        "Total: 52.345.678",
        "documento de 120 páginas",
    ],
)
def test_no_es_cedula(text):
    assert_no_type(text, T.CEDULA)


@pytest.mark.parametrize(
    ("text", "value"),
    [("pasaporte AB123456", "AB123456"), ("Pasaporte No. 987654321", "987654321")],
)
def test_pasaporte(text, value):
    assert_detects(text, T.PASAPORTE, value)


# --- NIT --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("identificada con NIT 900.123.456-7,", "900.123.456-7"),
        ("NIT: 900123456-7", "900123456-7"),
        ("Nit. 800.765.432 - 1", "800.765.432 - 1"),
        ("NIT No. 830123456", "830123456"),
        ("proveedor 800.765.432-1 registrado", "800.765.432-1"),
    ],
)
def test_nit(text, value):
    assert_detects(text, T.NIT, value)


def test_no_es_nit_un_valor_en_pesos():
    assert_no_type("Valor $ 900.123.456", T.NIT)


# --- Cuenta bancaria --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("cuenta de ahorros No. 123-456789-01", "123-456789-01"),
        ("Cta. Cte. 0012 3456 7890", "0012 3456 7890"),
        ("cuenta corriente número 4567891234", "4567891234"),
    ],
)
def test_cuenta(text, value):
    assert_detects(text, T.CUENTA, value)


# --- Fecha de nacimiento, fechas y edad -------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("nacido el 15/03/1985", "15/03/1985"),
        ("Fecha de nacimiento: 1985-03-15", "1985-03-15"),
        ("nació el 3 de marzo de 1990", "3 de marzo de 1990"),
        ("F. Nac. 02-07-79", "02-07-79"),
        ("nacida en Cali el 2.7.1979", "2.7.1979"),
    ],
)
def test_fecha_nacimiento(text, value):
    assert_detects(text, T.FECHA_NACIMIENTO, value)


def test_otras_fechas_no_se_anonimizan_por_defecto():
    text = "Firmado el 15/03/2024 en Bogotá."
    assert detect(text) == []


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("Firmado el 15/03/2024.", "15/03/2024"),
        ("inicio: 2024-01-31", "2024-01-31"),
        ("el 1 de febrero del 2024", "1 de febrero del 2024"),
    ],
)
def test_todas_las_fechas_si_se_activa(text, value):
    assert_detects(text, T.FECHA, value, anonymize_all_dates=True)


def test_fecha_nacimiento_gana_a_fecha_generica():
    found = detect("nacido el 15/03/1985", anonymize_all_dates=True)
    assert found == [(T.FECHA_NACIMIENTO, "15/03/1985")]


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("edad: 39", "39"),
        ("Edad 39 años", "39 años"),
        ("una persona de 45 años de edad", "45 años"),
        ("nacido el 15/03/1985 (39 años)", "39 años"),
    ],
)
def test_edad(text, value):
    assert_detects(text, T.EDAD, value)


@pytest.mark.parametrize("text", ["contrato a 2 años", "hace 10 años", "garantía de 5 años"])
def test_no_es_edad(text):
    assert_no_type(text, T.EDAD)


# --- Dirección --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("domicilio en Calle 45 # 12-34, Bogotá", "Calle 45 # 12-34"),
        ("Cra. 7 No. 12-34 Apto 501.", "Cra. 7 No. 12-34 Apto 501"),
        ("Carrera 15 #93-75", "Carrera 15 #93-75"),
        ("Av. Calle 26 # 59-51 Torre 3 Oficina 402", "Av. Calle 26 # 59-51 Torre 3 Oficina 402"),
        ("Diagonal 40A Sur # 20-15", "Diagonal 40A Sur # 20-15"),
        ("Transversal 5 bis # 10-20", "Transversal 5 bis # 10-20"),
        ("KR 50 N° 10-20", "KR 50 N° 10-20"),
    ],
)
def test_direccion(text, value):
    assert_detects(text, T.DIRECCION, value)


@pytest.mark.parametrize("text", ["la calle principal", "Calle 45", "en la carrera 7"])
def test_no_es_direccion(text):
    assert_no_type(text, T.DIRECCION)


# --- Empresa ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("Entre Soluciones Andinas S.A.S., identificada", "Soluciones Andinas S.A.S."),
        ("cliente del Banco de Bogotá S.A. desde", "Banco de Bogotá S.A."),
        ("Constructora El Roble Ltda. presenta", "Constructora El Roble Ltda."),
        ("Acme Corp, identificada con NIT 900.111.222-3", "Acme Corp"),
        ("Datos y Redes SAS", "Datos y Redes SAS"),
    ],
)
def test_empresa(text, value):
    assert_detects(text, T.EMPRESA, value)


@pytest.mark.parametrize("text", ["La empresa contratista", "Sociedad Anónima Simplificada"])
def test_no_es_empresa(text):
    assert_no_type(text, T.EMPRESA)


# --- Nombres de persona -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("representada por María Fernanda López Ruiz,", "María Fernanda López Ruiz"),
        ("atendido por el Sr. Pedro Ramírez hoy", "Pedro Ramírez"),
        ("la señora Ana María de la Torre firmó", "Ana María de la Torre"),
        ("y Juan Carlos Pérez Gómez, identificado con C.C. 1", "Juan Carlos Pérez Gómez"),
        ("Firma: Juan Carlos Pérez", "Juan Carlos Pérez"),
        ("Nombre completo: Laura Gómez", "Laura Gómez"),
        ("Dra. Camila Restrepo Vélez", "Camila Restrepo Vélez"),
    ],
)
def test_nombre(text, value):
    assert_detects(text, T.NOMBRE, value)


@pytest.mark.parametrize(
    "text", ["Entregar Informes Mensuales", "Cláusula Primera Objeto", "Bogotá, Colombia"]
)
def test_no_es_nombre(text):
    assert_no_type(text, T.NOMBRE)


# --- Contrato ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("Contrato de prestación de servicios No. CPS-2024-0153", "CPS-2024-0153"),
        ("según contrato N° 045-2023,", "045-2023"),
        ("Número de contrato: OC-7781", "OC-7781"),
        ("contrato número 2024/17", "2024/17"),
    ],
)
def test_contrato(text, value):
    assert_detects(text, T.CONTRATO, value)


@pytest.mark.parametrize(
    "text", ["el contrato no podrá cederse", "Contrato de arrendamiento", "contrato No. ABC"]
)
def test_no_es_contrato(text):
    assert_no_type(text, T.CONTRATO)


# --- Comportamiento general -------------------------------------------------------------


def test_coincidencias_no_cruzan_saltos_de_linea():
    text = "# Contrato No. CPS-1\n\nEntre Soluciones Andinas S.A.S., identificada"
    found = detect(text)
    assert (T.EMPRESA, "Soluciones Andinas S.A.S.") in found
    assert (T.CONTRATO, "CPS-1") in found


def test_single_line():
    assert single_line(r"a\s+b[\s.-]c[^\s]") == r"a[ \t]+b[ \t.-]c[^ \t]"
    assert single_line(r"\\s") == r"\\s"  # barra escapada: no es \s


def test_texto_sin_datos_no_cambia():
    text = "## Cláusulas\n\nEl objeto es prestar servicios de consultoría.\n"
    assert Anonymizer().anonymize(text) == text
