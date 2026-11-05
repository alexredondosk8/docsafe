from django.urls import path

from . import views

app_name = "llm"

urlpatterns = [
    path("configuracion/", views.settings_page, name="settings"),
    path("configuracion/probar/", views.test_connection, name="test_connection"),
]
