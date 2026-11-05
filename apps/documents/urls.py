from django.urls import path

from . import views

app_name = "documents"

urlpatterns = [
    path("", views.upload, name="upload"),
    path("historial/", views.history, name="history"),
    path("conversiones/<uuid:pk>/", views.detail, name="detail"),
    path("conversiones/<uuid:pk>/estado/", views.status, name="status"),
    path("conversiones/<uuid:pk>/descargar/", views.download, name="download"),
    path("conversiones/<uuid:pk>/eliminar/", views.delete, name="delete"),
]
