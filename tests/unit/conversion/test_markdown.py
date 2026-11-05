"""Pruebas de las utilidades de Markdown."""

import pytest

from apps.conversion.markdown import (
    escape_block_start,
    escape_cell,
    escape_inline,
    normalize,
    table_to_markdown,
)


def test_escape_inline():
    assert escape_inline(r"a*b`c\d") == r"a\*b\`c\\d"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("# no es título", "\\# no es título"),
        ("- no es lista", "\\- no es lista"),
        ("1. no es lista", "\\1. no es lista"),
        ("> no es cita", "\\> no es cita"),
        ("Texto normal # con almohadilla", "Texto normal # con almohadilla"),
        ("#hashtag", "#hashtag"),
    ],
)
def test_escape_block_start(text, expected):
    assert escape_block_start(text) == expected


def test_escape_cell():
    assert escape_cell("  a | b\r\nsegunda línea ") == "a \\| b<br>segunda línea"


def test_table_to_markdown_rellena_filas_cortas():
    md = table_to_markdown([["A", "B", "C"], ["1"]])
    assert md == "| A | B | C |\n|---|---|---|\n| 1 |  |  |"


def test_table_to_markdown_vacia():
    assert table_to_markdown([]) == ""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("identiﬁcada", "identificada\n"),  # ligadura "ﬁ"
        ("C.C. 52.345.678", "C.C. 52.345.678\n"),  # espacio duro
        ("a\r\nb", "a\nb\n"),
        ("a   \nb", "a\nb\n"),
        ("a\n\n\n\n\nb", "a\n\nb\n"),
        ("# Título\nTexto", "# Título\n\nTexto\n"),
        ("   \n\n  ", ""),
    ],
)
def test_normalize(raw, expected):
    assert normalize(raw) == expected
