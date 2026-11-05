"""Genera los documentos de ejemplo usados en las pruebas.

TODOS los datos son ficticios (nombres, cédulas, NIT, correos, teléfonos, direcciones).
Uso:  uv run python -m tests.fixtures.generate
"""

import datetime as dt
import io
from pathlib import Path

import openpyxl
import pymupdf
from docx import Document
from docx.enum.text import WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

HERE = Path(__file__).resolve().parent

EMPRESA = "Soluciones Andinas S.A.S."
NIT = "900.123.456-7"
CONTRATO = "CPS-2024-0153"
REPRESENTANTE = "María Fernanda López Ruiz"
CONTRATISTA = "Juan Carlos Pérez Gómez"
CEDULA_CONTRATISTA = "1.020.304.050"
CORREO = "juan.perez@ejemplo.com"
TELEFONO = "+57 310 555 1234"
DIRECCION = "Calle 45 # 12-34, Bogotá"

PARRAFO_PARTES = (
    f"Entre {EMPRESA}, identificada con NIT {NIT}, con domicilio en {DIRECCION}, "
    f"representada por {REPRESENTANTE}, identificada con C.C. 52.345.678, y "
    f"{CONTRATISTA}, identificado con C.C. {CEDULA_CONTRATISTA}, nacido el 15/03/1985 "
    f"(39 años), correo {CORREO} y teléfono {TELEFONO}, se celebra el presente contrato."
)


# --- DOCX -------------------------------------------------------------------------------


def _add_hyperlink(paragraph, url: str, text: str) -> None:
    part = paragraph.part
    r_id = part.relate_to(
        url,
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)
    run = OxmlElement("w:r")
    text_el = OxmlElement("w:t")
    text_el.text = text
    run.append(text_el)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)


def make_docx(path: Path) -> None:
    doc = Document()
    section = doc.sections[0]
    section.header.paragraphs[0].text = f"{EMPRESA} — NIT {NIT}"
    section.footer.paragraphs[0].text = "Documento confidencial"

    doc.add_heading(f"Contrato de prestación de servicios No. {CONTRATO}", level=1)
    doc.add_paragraph(PARRAFO_PARTES)

    doc.add_heading("Cláusulas", level=2)
    p = doc.add_paragraph()
    p.add_run("PRIMERA. Objeto: ").bold = True
    p.add_run("prestar servicios de ")
    p.add_run("consultoría").italic = True
    p.add_run(" en sistemas de información.")

    doc.add_paragraph("Entregar informes mensuales.", style="List Bullet")
    doc.add_paragraph("Asistir a reuniones de seguimiento.", style="List Bullet")
    doc.add_paragraph("Firma del acta de inicio.", style="List Number")
    doc.add_paragraph("Ejecución del servicio.", style="List Number")

    p = doc.add_paragraph("Línea uno")
    p.runs[0].add_break(WD_BREAK.LINE)
    p.add_run("Línea dos")

    doc.add_heading("Valores", level=2)
    table = doc.add_table(rows=4, cols=3)
    rows = [
        ("Concepto", "Valor", "Observación"),
        ("Honorarios", "$ 5.000.000", "Mensual | IVA incluido"),
        ("Viáticos", "$ 800.000", ""),
        ("Total", "", ""),
    ]
    for r, values in enumerate(rows):
        for c, value in enumerate(values):
            table.cell(r, c).text = value
    merged = table.cell(3, 1).merge(table.cell(3, 2))
    merged.text = "$ 5.800.000"

    p = doc.add_paragraph("Contacto: ")
    _add_hyperlink(p, f"mailto:{CORREO}", CORREO)

    doc.add_paragraph("")  # párrafo vacío: debe ignorarse
    doc.add_paragraph("*Texto con asteriscos* y # almohadilla")
    doc.save(path)


# --- XLSX -------------------------------------------------------------------------------


def make_xlsx(path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Empleados"
    ws.append(["Nombre", "Cédula", "Correo", "Fecha de nacimiento", "Salario", "Bono"])
    ws.append([CONTRATISTA, CEDULA_CONTRATISTA, CORREO, dt.date(1985, 3, 15), 5000000, None])
    ws.append(
        [
            REPRESENTANTE,
            "52.345.678",
            "maria.lopez@ejemplo.com",
            dt.date(1979, 7, 2),
            7250000.5,
            0.1,
        ]
    )
    ws.append(["Pedro | Ramírez", "79.111.222", None, None, None, None])
    ws["F2"] = "=E2*0.1"
    ws["A6"] = "Nota:\nfila con salto de línea"

    resumen = wb.create_sheet("Resumen")
    resumen.append(["Empresa", EMPRESA])
    resumen.append(["NIT", NIT])
    resumen.append(["Contrato", CONTRATO])

    wb.create_sheet("Vacía")

    oculta = wb.create_sheet("Oculta")
    oculta.append(["Dato", "Valor"])
    oculta.append(["Teléfono", TELEFONO])
    oculta.sheet_state = "hidden"
    wb.save(path)


# --- PDF --------------------------------------------------------------------------------

_PDF_HTML = f"""
<h1>Contrato de prestación de servicios No. {CONTRATO}</h1>
<p>{PARRAFO_PARTES}</p>
<h2>Cláusulas</h2>
<p><b>PRIMERA. Objeto:</b> prestar servicios de consultoría en sistemas de información.</p>
<ul>
  <li>Entregar informes mensuales.</li>
  <li>Asistir a reuniones de seguimiento.</li>
</ul>
<h2>Valores</h2>
<table border="1" cellpadding="4">
  <tr><th>Concepto</th><th>Valor</th></tr>
  <tr><td>Honorarios</td><td>$ 5.000.000</td></tr>
  <tr><td>Viáticos</td><td>$ 800.000</td></tr>
</table>
<p>Firma: {CONTRATISTA}</p>
"""


def _html_to_pdf(html: str) -> pymupdf.Document:
    story = pymupdf.Story(html=html)
    buffer = io.BytesIO()
    writer = pymupdf.DocumentWriter(buffer)
    rect = pymupdf.paper_rect("letter")
    where = rect + (54, 54, -54, -54)
    more = True
    while more:
        device = writer.begin_page(rect)
        more, _ = story.place(where)
        story.draw(device)
        writer.end_page()
    writer.close()
    return pymupdf.open("pdf", buffer.getvalue())


def _add_ruled_table_page(doc: pymupdf.Document) -> None:
    """Página con una tabla con bordes (como las de un PDF exportado desde Word)."""
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 60), "Anexo 1. Responsables", fontsize=14)
    rows = [
        ("Concepto", "Valor", "Responsable"),
        ("Honorarios", "$ 5.000.000", "Juan Pérez"),
        ("Viáticos", "$ 800.000", "María López"),
    ]
    x0, y0, w, h = 72, 80, 150, 22
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            rect = pymupdf.Rect(x0 + c * w, y0 + r * h, x0 + (c + 1) * w, y0 + (r + 1) * h)
            page.draw_rect(rect, color=(0, 0, 0), width=0.8)
            page.insert_text((rect.x0 + 4, rect.y1 - 7), value, fontsize=10)


def make_pdf(path: Path) -> None:
    doc = _html_to_pdf(_PDF_HTML)
    _add_ruled_table_page(doc)
    doc.set_metadata({"title": "Contrato", "author": REPRESENTANTE})
    doc.save(path)


def make_mixed_pdf(path: Path) -> None:
    """Una página con texto y otra solo con imagen (parcialmente escaneado)."""
    doc = _html_to_pdf("<p>Página con texto del contrato.</p>")
    _add_image_page(doc)
    doc.save(path)


def _add_image_page(doc: pymupdf.Document) -> None:
    page = doc.new_page()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 100), False)
    pix.set_rect(pix.irect, (200, 200, 200))
    page.insert_image(pymupdf.Rect(72, 72, 472, 272), pixmap=pix)


def make_scanned_pdf(path: Path) -> None:
    """PDF sin capa de texto (simula un escaneo): solo una imagen."""
    doc = pymupdf.open()
    _add_image_page(doc)
    doc.save(path)


def make_encrypted_pdf(path: Path) -> None:
    doc = _html_to_pdf("<p>Documento protegido.</p>")
    doc.save(
        path,
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        user_pw="clave-ficticia",
        owner_pw="clave-ficticia-2",
    )


def main() -> None:
    make_docx(HERE / "contrato.docx")
    make_xlsx(HERE / "empleados.xlsx")
    make_pdf(HERE / "contrato.pdf")
    make_scanned_pdf(HERE / "escaneado.pdf")
    make_mixed_pdf(HERE / "mixto.pdf")
    make_encrypted_pdf(HERE / "protegido.pdf")
    print("Documentos de ejemplo generados en", HERE)


if __name__ == "__main__":
    main()
