"""Rutas principales de DocSafe."""

from django.urls import include, path

urlpatterns = [
    path("", include("apps.documents.urls")),
]
