"""Content-Security-Policy y ausencia de JavaScript/estilos en línea."""

import re

import pytest
from django.urls import reverse

from apps.documents.models import Conversion

pytestmark = pytest.mark.django_db

INLINE = re.compile(r"\son[a-z]+=|\sstyle=|<script(?![^>]*\ssrc=)", re.IGNORECASE)


@pytest.fixture
def pages():
    review = Conversion.objects.create(
        original_filename="r.pdf",
        file_type="pdf",
        size_bytes=1,
        status=Conversion.Status.REVIEW,
        progress=100,
        review_text="Hola Juan",
        review_data={
            "entities": [
                {
                    "key": "e1",
                    "type": "NOMBRE",
                    "values": ["Juan"],
                    "sources": ["reglas"],
                    "count": 1,
                    "enabled": True,
                }
            ],
            "spans": [[5, 9, "e1"]],
        },
    )
    done = Conversion.objects.create(
        original_filename="c.pdf",
        file_type="pdf",
        size_bytes=1,
        status=Conversion.Status.COMPLETED,
        progress=100,
        markdown="Hola [NOMBRE_1]",
    )
    return [
        reverse("documents:upload"),
        reverse("documents:history"),
        reverse("llm:settings"),
        reverse("documents:detail", args=[review.id]),
        reverse("documents:detail", args=[done.id]),
    ]


def test_cabecera_csp_estricta(client, pages):
    for url in pages:
        csp = client.get(url)["Content-Security-Policy"]
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert "unsafe-inline" not in csp
        assert "frame-ancestors 'none'" in csp


def test_paginas_sin_javascript_ni_estilos_en_linea(client, pages):
    for url in pages:
        html = client.get(url).content.decode()
        assert not INLINE.search(html), (url, INLINE.search(html).group(0))


def test_confirmaciones_con_data_confirm(client, pages):
    review_html = client.get(pages[3]).content.decode()
    assert 'name="accion" value="confirmar"' in review_html
    assert "data-confirm=" in review_html
