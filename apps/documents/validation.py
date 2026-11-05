"""Validación de archivos subidos.

Python puro (sin Django) para poder probarlo de forma aislada. El tipo real se comprueba
por el contenido del archivo, no solo por la extensión:

- PDF: debe contener la cabecera ``%PDF-`` al inicio.
- DOCX / XLSX: deben ser ZIP con ``[Content_Types].xml`` que declare el documento principal
  correcto. Esto rechaza también variantes con macros (.docm/.xlsm) renombradas.

No se usa python-magic porque en Windows necesita una DLL externa (libmagic).
"""

import re
import zipfile
from pathlib import PurePath
from typing import BinaryIO

ALLOWED_EXTENSIONS = ("pdf", "docx", "xlsx")

# Tipo de contenido principal que debe declarar [Content_Types].xml.
_OOXML_MAIN_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
}

# Cabecera de los archivos OLE (formatos antiguos .doc/.xls y Office con contraseña).
_OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

# Protección contra "bombas ZIP" (archivos que se expanden de forma desmedida).
MAX_ZIP_ENTRIES = 10_000
MAX_ZIP_UNCOMPRESSED_BYTES = 500 * 1024 * 1024

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class InvalidFileError(Exception):
    """El archivo no es válido. El mensaje se muestra al usuario tal cual."""


def clean_filename(name: str) -> str:
    """Devuelve solo el nombre base, sin rutas ni caracteres de control, máx. 255 caracteres."""
    base = PurePath(name.replace("\\", "/")).name
    base = _CONTROL_CHARS.sub("", base).strip()
    if len(base) > 255:
        stem, dot, ext = base.rpartition(".")
        base = (stem[: 255 - len(ext) - 1] + dot + ext) if dot else base[:255]
    return base


def get_extension(name: str) -> str:
    suffix = PurePath(name).suffix.lower()
    return suffix[1:] if suffix else ""


def validate_upload(name: str, size: int, fileobj: BinaryIO, max_bytes: int) -> str:
    """Valida un archivo y devuelve su tipo (``pdf``, ``docx`` o ``xlsx``).

    Lanza ``InvalidFileError`` con un mensaje en español si no es válido.
    """
    filename = clean_filename(name or "")
    if not filename:
        raise InvalidFileError("El archivo no tiene nombre.")

    ext = get_extension(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise InvalidFileError(
            "Formato no permitido. Solo se aceptan archivos .pdf, .docx y .xlsx."
        )

    if size <= 0:
        raise InvalidFileError("El archivo está vacío.")
    if size > max_bytes:
        max_mb = max_bytes / (1024 * 1024)
        raise InvalidFileError(f"El archivo supera el tamaño máximo de {max_mb:g} MB.")

    fileobj.seek(0)
    head = fileobj.read(1024)
    fileobj.seek(0)

    if head.startswith(_OLE_SIGNATURE):
        raise InvalidFileError(
            "El archivo está protegido con contraseña o usa un formato antiguo "
            "(.doc/.xls), que no se admite en esta versión."
        )

    if ext == "pdf":
        _check_pdf(head)
    else:
        _check_ooxml(fileobj, ext)
    fileobj.seek(0)
    return ext


def _check_pdf(head: bytes) -> None:
    if b"%PDF-" not in head:
        raise InvalidFileError("El contenido del archivo no corresponde a un PDF.")


def _check_ooxml(fileobj: BinaryIO, ext: str) -> None:
    mismatch = InvalidFileError(f"El contenido del archivo no corresponde a un archivo .{ext}.")
    if not zipfile.is_zipfile(fileobj):
        raise mismatch
    fileobj.seek(0)
    try:
        with zipfile.ZipFile(fileobj) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_ZIP_ENTRIES:
                raise InvalidFileError("El archivo tiene una estructura interna demasiado grande.")
            if sum(i.file_size for i in infos) > MAX_ZIP_UNCOMPRESSED_BYTES:
                raise InvalidFileError("El archivo tiene una estructura interna demasiado grande.")
            try:
                info = zf.getinfo("[Content_Types].xml")
            except KeyError:
                raise mismatch from None
            if info.file_size > 1024 * 1024:
                raise mismatch
            content_types = zf.read(info).decode("utf-8", errors="replace")
    except zipfile.BadZipFile:
        raise mismatch from None

    if _OOXML_MAIN_TYPES[ext] not in content_types:
        raise mismatch
