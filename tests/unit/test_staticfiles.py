"""Versión en las URL de CSS/JS."""

import re

import pytest
from django.templatetags.static import static
from django.urls import reverse

from config import staticfiles


def test_url_lleva_huella_del_contenido():
    url = static("css/app.css")
    assert re.fullmatch(r"/static/css/app\.css\?v=[0-9a-f]{12}", url)


def test_huella_cambia_si_cambia_el_archivo(tmp_path, monkeypatch):
    css = tmp_path / "a.css"
    css.write_text("body{}")
    monkeypatch.setattr(staticfiles.finders, "find", lambda name: str(css))
    first = staticfiles.static_version("a.css")
    css.write_text("body{color:red}")
    assert staticfiles.static_version("a.css") != first


def test_archivo_inexistente_sin_version():
    assert static("no/existe.css") == "/static/no/existe.css"


@pytest.mark.django_db
def test_paginas_usan_urls_versionadas_y_se_sirven(client):
    html = client.get(reverse("documents:upload")).content.decode()
    urls = re.findall(r'(?:href|src)="(/static/[^"]+)"', html)
    assert urls and all("?v=" in u for u in urls)
    for url in urls:
        assert client.get(url).status_code == 200
