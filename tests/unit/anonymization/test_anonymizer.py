"""Pruebas del motor: etiquetas consistentes, propagación, solapamientos, tablas y configuración."""

from pathlib import Path

import pytest

from apps.anonymization import Anonymizer, AnonymizerConfig, EntityMap, EntityType
from apps.anonymization.anonymizer import resolve_overlaps
from apps.anonymization.entities import Span, normalize_value
from apps.anonymization.tables import detect_in_tables, header_type
from apps.conversion import convert

T = EntityType
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


# --- Mapa de entidades ------------------------------------------------------------------


def test_misma_entidad_misma_etiqueta_y_numeracion_por_tipo():
    m = EntityMap()
    assert m.label_for(T.NOMBRE, "Juan Pérez") == "[NOMBRE_1]"
    assert m.label_for(T.CORREO, "a@b.co") == "[CORREO_1]"
    assert m.label_for(T.NOMBRE, "Ana Ruiz") == "[NOMBRE_2]"
    assert m.label_for(T.NOMBRE, "JUAN  PEREZ") == "[NOMBRE_1]"
    entity = next(e for e in m.entities if e.label == "[NOMBRE_1]")
    assert entity.count == 2
    assert entity.values == ["Juan Pérez", "JUAN  PEREZ"]


def test_clear_borra_valores_reales():
    m = EntityMap()
    m.label_for(T.NOMBRE, "Juan Pérez")
    m.clear()
    assert m.entities == []
    assert m.label_for(T.NOMBRE, "Otro") == "[NOMBRE_1]"


@pytest.mark.parametrize(
    ("entity_type", "a", "b"),
    [
        (T.CEDULA, "1.020.304.050", "1020304050"),
        (T.NIT, "900.123.456-7", "900123456"),
        (T.TELEFONO, "+57 310 555 1234", "3105551234"),
        (T.CORREO, "Juan.Perez@Ejemplo.com", "juan.perez@ejemplo.com"),
        (T.EMPRESA, "Soluciones Andinas S.A.S.", "SOLUCIONES ANDINAS SAS"),
        (T.NOMBRE, "María López", "maria lopez"),
    ],
)
def test_normalizacion_equivalente(entity_type, a, b):
    assert normalize_value(entity_type, a) == normalize_value(entity_type, b)


# --- Propagación y consistencia ---------------------------------------------------------


def test_nombre_de_tabla_se_reemplaza_en_el_texto():
    text = (
        "| Nombre | Cargo |\n|---|---|\n| Laura Gómez Ríos | Analista |\n\n"
        "La analista Laura Gómez Ríos entregó el informe."
    )
    out = Anonymizer().anonymize(text)
    assert "Laura" not in out
    assert out.count("[NOMBRE_1]") == 2


def test_cedula_con_otro_formato_recibe_misma_etiqueta():
    text = "C.C. 1.020.304.050 ... firma del titular 1020304050"
    out = Anonymizer().anonymize(text)
    assert out == "C.C. [CEDULA_1] ... firma del titular [CEDULA_1]"


def test_nit_sin_digito_de_verificacion_misma_etiqueta():
    out = Anonymizer().anonymize("NIT 900.123.456-7 y luego 900123456")
    assert out == "NIT [NIT_1] y luego [NIT_1]"


def test_edad_no_se_propaga():
    out = Anonymizer().anonymize("Edad: 39. Hay 39 sillas.")
    assert out == "Edad: [EDAD_1]. Hay 39 sillas."


def test_mapa_compartido_entre_fragmentos():
    anonymizer = Anonymizer()
    first = anonymizer.anonymize("correo: ana@x.co")
    second = anonymizer.anonymize("de nuevo ana@x.co y luis@x.co")
    assert first == "correo: [CORREO_1]"
    assert second == "de nuevo [CORREO_1] y [CORREO_2]"


def test_etiquetas_por_orden_de_aparicion():
    out = Anonymizer().anonymize("b@x.co, a@x.co")
    assert out == "[CORREO_1], [CORREO_2]"


# --- Solapamientos ----------------------------------------------------------------------


def test_gana_mayor_prioridad_y_luego_mayor_longitud():
    spans = [
        Span(0, 10, T.NOMBRE, priority=30),
        Span(5, 8, T.CORREO, priority=90),
        Span(12, 20, T.CEDULA, priority=70),
        Span(12, 18, T.CEDULA, priority=70),
    ]
    result = resolve_overlaps(spans)
    assert [(s.start, s.end, s.type) for s in result] == [(5, 8, T.CORREO), (12, 20, T.CEDULA)]


# --- Tablas -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Nombre", T.NOMBRE),
        ("Nombres y apellidos", T.NOMBRE),
        ("Cédula", T.CEDULA),
        ("No. de documento", T.CEDULA),
        ("NIT", T.NIT),
        ("Correo electrónico", T.CORREO),
        ("E-mail", T.CORREO),
        ("Teléfono", T.TELEFONO),
        ("Celular", T.TELEFONO),
        ("Dirección", T.DIRECCION),
        ("Fecha de nacimiento", T.FECHA_NACIMIENTO),
        ("Edad", T.EDAD),
        ("No. Contrato", T.CONTRATO),
        ("Razón social", T.EMPRESA),
        ("Concepto", None),
        ("Valor", None),
        ("ID", None),
    ],
)
def test_tipo_por_cabecera(header, expected):
    assert header_type(header) == expected


def test_columnas_sensibles_y_no_sensibles():
    text = (
        "| Nombre | Salario | Correo |\n|---|---|---|\n"
        "| Ana Ruiz | 5000000 | ana@x.co |\n| - |  | N/A |"
    )
    out = Anonymizer().anonymize(text)
    assert out == (
        "| Nombre | Salario | Correo |\n|---|---|---|\n"
        "| [NOMBRE_1] | 5000000 | [CORREO_1] |\n| - |  | N/A |"
    )


def test_tabla_clave_valor():
    text = "| Empresa | Tecnologías Delta |\n|---|---|\n| NIT | 830.111.222-3 |\n| Ciudad | Cali |"
    out = Anonymizer().anonymize(text)
    assert out == "| Empresa | [EMPRESA_1] |\n|---|---|\n| NIT | [NIT_1] |\n| Ciudad | Cali |"


def test_tabla_sin_espacios_y_pipe_escapado():
    text = "|Responsable|Valor|\n|---|---|\n|Pedro \\| Ramírez|$ 800.000|"
    spans = detect_in_tables(text)
    assert [(s.type, text[s.start : s.end]) for s in spans] == [(T.NOMBRE, "Pedro \\| Ramírez")]


def test_texto_que_no_es_tabla():
    assert detect_in_tables("Esto | no es | una tabla\nsin separador") == []


# --- Configuración ----------------------------------------------------------------------


def test_tipos_desactivados():
    config = AnonymizerConfig(disabled_types=frozenset({T.CORREO}))
    out = Anonymizer(config).anonymize("ana@x.co, C.C. 52.345.678")
    assert out == "ana@x.co, C.C. [CEDULA_1]"


# --- Documentos de ejemplo: ningún dato ficticio debe sobrevivir ------------------------

SENSITIVE_VALUES = [
    "Soluciones Andinas",
    "900.123.456",
    "María Fernanda",
    "López Ruiz",
    "52.345.678",
    "Juan Carlos",
    "Pérez Gómez",
    "1.020.304.050",
    "15/03/1985",
    "1985-03-15",
    "1979-07-02",
    "39 años",
    "juan.perez@ejemplo.com",
    "maria.lopez@ejemplo.com",
    "310 555 1234",
    "Calle 45 # 12-34",
    "CPS-2024-0153",
    "79.111.222",
    "Juan Pérez",
    "María López",
    "Ramírez",
]


@pytest.mark.parametrize(
    ("name", "file_type"),
    [("contrato.docx", "docx"), ("empleados.xlsx", "xlsx"), ("contrato.pdf", "pdf")],
)
def test_documentos_de_ejemplo_sin_datos_personales(name, file_type):
    markdown = convert(FIXTURES / name, file_type).markdown
    out = Anonymizer().anonymize(markdown)
    leaked = [v for v in SENSITIVE_VALUES if v in out]
    assert leaked == [], f"Datos sin anonimizar en {name}: {leaked}"


def test_documento_conserva_contenido_no_sensible():
    markdown = convert(FIXTURES / "contrato.docx", "docx").markdown
    out = Anonymizer().anonymize(markdown)
    for text in ["## Cláusulas", "**PRIMERA. Objeto:**", "| Honorarios | $ 5.000.000 |"]:
        assert text in out
