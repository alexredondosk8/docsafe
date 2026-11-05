"""Pruebas de la división en fragmentos."""

import pytest

from apps.anonymization.chunking import split_into_chunks


def _check_cover(text, chunks):
    """Los fragmentos son trozos exactos del original, en orden y sin huecos de contenido."""
    for chunk in chunks:
        assert text[chunk.start : chunk.end] == chunk.text
    joined = "".join(c.text for c in chunks)
    assert joined.split() == text.split()


def test_texto_corto_un_fragmento():
    text = "# Título\n\nUn párrafo."
    chunks = split_into_chunks(text, 2500)
    assert len(chunks) == 1
    assert chunks[0].start == 0
    assert chunks[0].text == text


def test_respeta_parrafos():
    paragraphs = [f"Párrafo {i} " + "palabra " * 20 for i in range(10)]
    text = "\n\n".join(paragraphs)
    chunks = split_into_chunks(text, 400)
    assert len(chunks) > 1
    _check_cover(text, chunks)
    for chunk in chunks:
        assert len(chunk.text) <= 400
        # ningún párrafo queda partido
        for paragraph in paragraphs:
            assert paragraph in text
            assert chunk.text.count(paragraph[:12]) in (0, 1)


def test_tabla_no_se_parte_si_cabe():
    table = "| Nombre | Cédula |\n|---|---|\n" + "\n".join(f"| P{i} | {i} |" for i in range(8))
    text = "Antes " * 30 + "\n\n" + table + "\n\nDespués " * 5
    chunks = split_into_chunks(text, 250)
    assert any(table in c.text for c in chunks)
    _check_cover(text, chunks)


def test_bloque_enorme_se_corta_por_lineas_y_espacios():
    text = "\n".join("línea " * 30 for _ in range(10)) + "\n\n" + "x" * 500
    chunks = split_into_chunks(text, 200)
    _check_cover(text, chunks)
    assert all(len(c.text) <= 200 for c in chunks)


def test_texto_vacio():
    assert split_into_chunks("", 2500) == []
    assert split_into_chunks("\n\n\n", 2500) == []


def test_tamano_minimo():
    with pytest.raises(ValueError):
        split_into_chunks("hola", 10)
