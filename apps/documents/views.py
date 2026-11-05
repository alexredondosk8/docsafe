"""Vistas de la app de documentos."""

from django.shortcuts import render


def home(request):
    """Página de inicio. En la Fase 1 se convierte en la pantalla de subida."""
    return render(request, "documents/home.html")
