"""Pruebas unitarias de la validación de archivos subidos."""

import io

import pytest

from apps.documents import validation
from apps.documents.validation import InvalidFileError, clean_filename, validate_upload
from tests import files

MB = 1024 * 1024


def validate(name: str, data: bytes, max_bytes: int = 20 * MB) -> str:
    return validate_upload(name, len(data), io.BytesIO(data), max_bytes)


# --- Archivos válidos -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "data", "expected"),
    [
        ("informe.pdf", files.pdf_bytes(), "pdf"),
        ("INFORME.PDF", files.pdf_bytes(), "pdf"),
        ("carta.docx", files.docx_bytes(), "docx"),
        ("datos.xlsx", files.xlsx_bytes(), "xlsx"),
        ("datos.Xlsx", files.xlsx_bytes(), "xlsx"),
    ],
)
def test_acepta_archivos_validos(name, data, expected):
    assert validate(name, data) == expected


def test_acepta_pdf_con_bytes_previos_a_la_cabecera():
    assert validate("a.pdf", b"\n\n" + files.pdf_bytes()) == "pdf"


def test_deja_el_archivo_al_inicio():
    stream = io.BytesIO(files.docx_bytes())
    validate_upload("a.docx", len(stream.getvalue()), stream, 20 * MB)
    assert stream.tell() == 0


# --- Extensión --------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["a.doc", "a.xls", "a.txt", "a.docm", "a.xlsm", "sin_extension"])
def test_rechaza_extensiones_no_permitidas(name):
    with pytest.raises(InvalidFileError, match="Formato no permitido"):
        validate(name, files.pdf_bytes())


def test_rechaza_nombre_vacio():
    with pytest.raises(InvalidFileError, match="no tiene nombre"):
        validate("", files.pdf_bytes())


# --- Tamaño -----------------------------------------------------------------------------


def test_rechaza_archivo_vacio():
    with pytest.raises(InvalidFileError, match="vacío"):
        validate("a.pdf", b"")


def test_rechaza_archivo_mayor_al_limite():
    data = files.pdf_bytes()
    with pytest.raises(InvalidFileError, match="tamaño máximo de 20 MB"):
        validate_upload("a.pdf", 20 * MB + 1, io.BytesIO(data), 20 * MB)


def test_acepta_archivo_exactamente_en_el_limite():
    data = files.pdf_bytes()
    assert validate_upload("a.pdf", 20 * MB, io.BytesIO(data), 20 * MB) == "pdf"


# --- Tipo real (contenido) --------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("falso.pdf", b"esto es texto plano, no un PDF"),
        ("falso.pdf", files.docx_bytes()),
        ("falso.docx", files.pdf_bytes()),
        ("falso.docx", files.xlsx_bytes()),
        ("falso.xlsx", files.docx_bytes()),
        ("macros.docx", files.ooxml_bytes(files.DOCM_MAIN)),
        ("sin_tipos.docx", files.ooxml_bytes(None, {"word/document.xml": b"x"})),
        ("roto.xlsx", b"PK\x03\x04" + b"\x00" * 100),
    ],
)
def test_rechaza_contenido_que_no_corresponde(name, data):
    with pytest.raises(InvalidFileError, match="no corresponde"):
        validate(name, data)


@pytest.mark.parametrize("name", ["antiguo.docx", "clave.xlsx", "x.pdf"])
def test_rechaza_ole_protegido_o_antiguo(name):
    with pytest.raises(InvalidFileError, match="contraseña o usa un formato antiguo"):
        validate(name, files.OLE_HEADER + b"\x00" * 600)


def test_rechaza_zip_con_demasiadas_entradas(monkeypatch):
    monkeypatch.setattr(validation, "MAX_ZIP_ENTRIES", 3)
    data = files.ooxml_bytes(files.DOCX_MAIN, {f"f{i}.xml": b"x" for i in range(5)})
    with pytest.raises(InvalidFileError, match="demasiado grande"):
        validate("a.docx", data)


def test_rechaza_zip_que_se_expande_demasiado(monkeypatch):
    monkeypatch.setattr(validation, "MAX_ZIP_UNCOMPRESSED_BYTES", 1000)
    data = files.ooxml_bytes(files.DOCX_MAIN, {"grande.xml": b"0" * 5000})
    with pytest.raises(InvalidFileError, match="demasiado grande"):
        validate("a.docx", data)


# --- Limpieza del nombre ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("informe.pdf", "informe.pdf"),
        ("C:\\Users\\yo\\Documentos\\informe.pdf", "informe.pdf"),
        ("../../etc/informe.pdf", "informe.pdf"),
        ("  con espacios.docx  ", "con espacios.docx"),
        ("ctrl\x00\x1f.xlsx", "ctrl.xlsx"),
        ("Año_Contratación.pdf", "Año_Contratación.pdf"),
    ],
)
def test_limpia_nombre(raw, expected):
    assert clean_filename(raw) == expected


def test_trunca_nombres_largos_conservando_extension():
    result = clean_filename("a" * 300 + ".docx")
    assert len(result) == 255
    assert result.endswith(".docx")
