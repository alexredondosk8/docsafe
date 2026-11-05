"""Word (.docx) → Markdown con python-docx.

Conserva el orden del documento: títulos, párrafos (negrita/cursiva), listas con viñetas o
numeradas, tablas y enlaces. Incluye encabezados y pies de página (separados con ``---``),
porque suelen contener datos de la empresa que luego se anonimizan.

No incluye (MVP): imágenes, cuadros de texto, notas al pie, comentarios ni control de cambios.
"""

import re
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.hyperlink import Hyperlink
from docx.text.paragraph import Paragraph

from .base import ConversionError, ConversionResult
from .markdown import escape_block_start, escape_cell, escape_inline, table_to_markdown

_HEADING_STYLE = re.compile(r"^(?:heading|t[íi]tulo|encabezado)\s*(\d)$", re.IGNORECASE)
_TITLE_STYLE = re.compile(r"^(?:title|t[íi]tulo)$", re.IGNORECASE)
_PLAIN_LINK_SCHEMES = ("mailto:", "tel:")


def convert_docx(path: Path) -> ConversionResult:
    try:
        document = Document(str(path))
    except Exception as exc:
        raise ConversionError("No se pudo abrir el documento de Word. Puede estar dañado.") from exc
    return ConversionResult(markdown=_DocxConverter(document).convert())


class _DocxConverter:
    def __init__(self, document):
        self.document = document
        self._numbering = self._load_numbering()

    # --- Documento completo -------------------------------------------------------------

    def convert(self) -> str:
        body = self._render_blocks(self.document.element.body, self.document._body)
        headers, footers = self._headers_and_footers()
        parts = [p for p in (headers, body, footers) if p]
        if not body:
            raise ConversionError("El documento de Word no contiene texto.")
        return "\n\n---\n\n".join(parts)

    def _headers_and_footers(self) -> tuple[str, str]:
        headers: list[str] = []
        footers: list[str] = []
        for section in self.document.sections:
            for target, items in (
                (headers, (section.first_page_header, section.header, section.even_page_header)),
                (footers, (section.first_page_footer, section.footer, section.even_page_footer)),
            ):
                for item in items:
                    if item.is_linked_to_previous:
                        continue
                    rendered = self._render_blocks(item._element, item)
                    if rendered and rendered not in target:
                        target.append(rendered)
        return "\n\n".join(headers), "\n\n".join(footers)

    # --- Bloques ------------------------------------------------------------------------

    def _iter_blocks(self, element, parent):
        for child in element.iterchildren():
            if child.tag == qn("w:p"):
                yield Paragraph(child, parent)
            elif child.tag == qn("w:tbl"):
                yield Table(child, parent)
            elif child.tag == qn("w:sdt"):  # controles de contenido
                content = child.find(qn("w:sdtContent"))
                if content is not None:
                    yield from self._iter_blocks(content, parent)

    def _render_blocks(self, element, parent) -> str:
        out: list[str] = []
        previous_list = None  # "-" o "1." si el bloque anterior era un elemento de lista
        for block in self._iter_blocks(element, parent):
            if isinstance(block, Table):
                rendered, list_marker = self._render_table(block), None
            else:
                rendered, list_marker = self._render_paragraph(block)
            if not rendered:
                continue
            # Elementos seguidos de la misma lista van juntos; si cambia el tipo, nueva lista.
            same_list = list_marker is not None and list_marker == previous_list
            out.append(("\n" if same_list else "\n\n" if out else "") + rendered)
            previous_list = list_marker
        return "".join(out)

    def _render_paragraph(self, paragraph: Paragraph) -> tuple[str, str | None]:
        text = self._render_inline(paragraph).strip()
        if not text:
            return "", None
        level = self._heading_level(paragraph)
        if level:
            plain = escape_inline(" ".join(paragraph.text.split()))
            return "#" * level + " " + plain, None
        list_info = self._list_info(paragraph)
        if list_info:
            ilvl, ordered = list_info
            marker = "1." if ordered else "-"
            return "  " * ilvl + f"{marker} {text}", marker
        return escape_block_start(text), None

    # --- Texto con formato --------------------------------------------------------------

    def _render_inline(self, paragraph: Paragraph) -> str:
        segments: list[tuple[str, bool, bool]] = []  # (texto, negrita, cursiva)
        for item in paragraph.iter_inner_content():
            if isinstance(item, Hyperlink):
                segments.append((self._render_link(item), False, False))
            else:
                text = escape_inline(item.text.replace("\t", " "))
                segments.append((text, bool(item.bold), bool(item.italic)))

        merged: list[list] = []
        for text, bold, italic in segments:
            if merged and merged[-1][1] == bold and merged[-1][2] == italic:
                merged[-1][0] += text
            else:
                merged.append([text, bold, italic])
        return "".join(_wrap(text, bold, italic) for text, bold, italic in merged)

    def _render_link(self, link: Hyperlink) -> str:
        text = escape_inline(link.text)
        address = link.address or ""
        if link.fragment:
            address = f"{address}#{link.fragment}" if address else ""
        if not address or address.lower().startswith(_PLAIN_LINK_SCHEMES) or address == link.text:
            return text or address
        return f"[{text}]({address})"

    # --- Estilos: títulos y listas ------------------------------------------------------

    @staticmethod
    def _style_chain(paragraph: Paragraph):
        style = paragraph.style
        seen = 0
        while style is not None and seen < 10:
            yield style
            style = style.base_style
            seen += 1

    def _heading_level(self, paragraph: Paragraph) -> int:
        for style in self._style_chain(paragraph):
            name = (style.name or "").strip()
            if _TITLE_STYLE.match(name):
                return 1
            match = _HEADING_STYLE.match(name)
            if match:
                return min(max(int(match.group(1)), 1), 6)
        p_pr = paragraph._p.pPr
        outline = p_pr.find(qn("w:outlineLvl")) if p_pr is not None else None
        if outline is not None:
            level = int(outline.get(qn("w:val"), "9"))
            if level < 6:
                return level + 1
        return 0

    def _list_info(self, paragraph: Paragraph) -> tuple[int, bool] | None:
        num_pr = None
        p_pr = paragraph._p.pPr
        if p_pr is not None and p_pr.numPr is not None:
            num_pr = p_pr.numPr
        else:
            for style in self._style_chain(paragraph):
                s_pr = style.element.pPr
                if s_pr is not None and s_pr.numPr is not None:
                    num_pr = s_pr.numPr
                    break
        if num_pr is None:
            return None
        num_id = num_pr.numId.val if num_pr.numId is not None else None
        if not num_id:  # numId 0 = "sin lista"
            return None
        ilvl = num_pr.ilvl.val if num_pr.ilvl is not None else 0
        fmt = self._numbering.get((num_id, ilvl))
        if fmt is None:
            style_name = (paragraph.style.name or "").lower() if paragraph.style else ""
            ordered = "number" in style_name or "núm" in style_name
        else:
            ordered = fmt not in {"bullet", "none"}
        return min(ilvl, 8), ordered

    def _load_numbering(self) -> dict[tuple[int, int], str]:
        """Mapa (numId, nivel) → formato ('bullet', 'decimal', ...)."""
        try:
            numbering = self.document.part.numbering_part.element
        except (NotImplementedError, KeyError, AttributeError):
            return {}
        abstract: dict[str, dict[int, str]] = {}
        for abs_el in numbering.findall(qn("w:abstractNum")):
            levels = {}
            for lvl in abs_el.findall(qn("w:lvl")):
                fmt_el = lvl.find(qn("w:numFmt"))
                levels[int(lvl.get(qn("w:ilvl"), "0"))] = (
                    fmt_el.get(qn("w:val")) if fmt_el is not None else "bullet"
                )
            abstract[abs_el.get(qn("w:abstractNumId"))] = levels
        result = {}
        for num in numbering.findall(qn("w:num")):
            abs_id_el = num.find(qn("w:abstractNumId"))
            if abs_id_el is None:
                continue
            for ilvl, fmt in abstract.get(abs_id_el.get(qn("w:val")), {}).items():
                result[(int(num.get(qn("w:numId"))), ilvl)] = fmt
        return result

    # --- Tablas -------------------------------------------------------------------------

    def _render_table(self, table: Table) -> str:
        rows = []
        for row in table.rows:
            cells, previous_tc = [], None
            for cell in row.cells:
                # Celdas combinadas horizontalmente se repiten: solo se escribe la primera.
                cells.append("" if cell._tc is previous_tc else self._cell_text(cell))
                previous_tc = cell._tc
            rows.append(cells)
        if not any(any(c for c in r) for r in rows):
            return ""
        return table_to_markdown(rows)

    def _cell_text(self, cell) -> str:
        parts = []
        for block in self._iter_blocks(cell._tc, cell):
            if isinstance(block, Table):  # tabla anidada: se aplana
                for row in block.rows:
                    parts.append(" / ".join(c.text.strip() for c in row.cells if c.text.strip()))
            else:
                text = self._render_inline(block).strip()
                if text:
                    parts.append(text)
        return escape_cell("\n".join(p for p in parts if p))


def _wrap(text: str, bold: bool, italic: bool) -> str:
    """Aplica **negrita** / *cursiva* dejando los espacios de los extremos fuera."""
    if not (bold or italic) or not text.strip():
        return text
    lead = text[: len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()) :]
    core = text.strip()
    marker = "***" if bold and italic else "**" if bold else "*"
    return f"{lead}{marker}{core}{marker}{trail}"
