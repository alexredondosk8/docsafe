"""Pruebas de integración de la página de inicio."""

from django.urls import reverse


def test_inicio_responde_en_espanol(client):
    response = client.get(reverse("documents:home"))
    assert response.status_code == 200
    content = response.content.decode()
    assert '<html lang="es">' in content
    assert "DocSafe" in content


def test_inicio_no_carga_recursos_externos(client):
    """La interfaz funciona sin internet: no debe pedir CSS/JS a CDN."""
    content = client.get(reverse("documents:home")).content.decode()
    assert "cdn." not in content
    assert "https://" not in content


def test_rechaza_hosts_no_locales(client):
    response = client.get(reverse("documents:home"), HTTP_HOST="evil.example.com")
    assert response.status_code == 400
