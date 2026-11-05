"""Pruebas de integración de las páginas generales."""

import pytest
from django.urls import reverse

PAGES = ["documents:upload", "documents:history"]


@pytest.mark.django_db
@pytest.mark.parametrize("name", PAGES)
def test_paginas_responden_en_espanol(client, name):
    response = client.get(reverse(name))
    assert response.status_code == 200
    content = response.content.decode()
    assert '<html lang="es">' in content
    assert "DocSafe" in content


@pytest.mark.django_db
@pytest.mark.parametrize("name", PAGES)
def test_paginas_no_cargan_recursos_externos(client, name):
    """La interfaz funciona sin internet: no debe pedir CSS/JS a CDN."""
    content = client.get(reverse(name)).content.decode()
    assert "cdn." not in content
    assert "https://" not in content


def test_rechaza_hosts_no_locales(client):
    response = client.get(reverse("documents:upload"), HTTP_HOST="evil.example.com")
    assert response.status_code == 400
