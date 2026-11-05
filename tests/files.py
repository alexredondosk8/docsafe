"""Generadores de archivos mínimos para pruebas (sin datos reales)."""

import io
import zipfile

DOCX_MAIN = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
XLSX_MAIN = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
DOCM_MAIN = "application/vnd.ms-word.document.macroEnabled.main+xml"

OLE_HEADER = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def pdf_bytes() -> bytes:
    return b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def ooxml_bytes(main_type: str | None, extra: dict[str, bytes] | None = None) -> bytes:
    """ZIP con un [Content_Types].xml que declara ``main_type`` (o sin él si es None)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        if main_type is not None:
            zf.writestr(
                "[Content_Types].xml",
                '<?xml version="1.0"?><Types><Override PartName="/main.xml" '
                f'ContentType="{main_type}"/></Types>',
            )
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return buffer.getvalue()


def docx_bytes() -> bytes:
    return ooxml_bytes(DOCX_MAIN, {"word/document.xml": b"<w:document/>"})


def xlsx_bytes() -> bytes:
    return ooxml_bytes(XLSX_MAIN, {"xl/workbook.xml": b"<workbook/>"})
