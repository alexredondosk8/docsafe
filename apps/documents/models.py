"""Modelos de la app de documentos."""

import os
import uuid
from pathlib import Path

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.db import models


class UploadsStorage(FileSystemStorage):
    """Almacenamiento en settings.UPLOADS_DIR, leído en cada uso (las pruebas lo cambian)."""

    @property
    def base_location(self):
        return str(settings.UPLOADS_DIR)

    @property
    def location(self):
        return os.path.abspath(self.base_location)


def _uploads_storage():
    return UploadsStorage()


def _upload_to(instance, filename):
    """Nombre aleatorio en disco: el nombre original nunca se usa como ruta."""
    return f"{instance.id}.{instance.file_type}"


class Conversion(models.Model):
    """Una conversión de un documento a Markdown anonimizado."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        CONVERTING = "converting", "Convirtiendo"
        ANONYMIZING = "anonymizing", "Anonimizando"
        REVIEW = "review", "En revisión"
        COMPLETED = "completed", "Completado"
        ERROR = "error", "Error"

    class FileType(models.TextChoices):
        PDF = "pdf", "PDF"
        DOCX = "docx", "Word (.docx)"
        XLSX = "xlsx", "Excel (.xlsx)"

    id = models.UUIDField("identificador", primary_key=True, default=uuid.uuid4, editable=False)
    original_filename = models.CharField("nombre original", max_length=255)
    file_type = models.CharField("tipo", max_length=10, choices=FileType.choices)
    size_bytes = models.PositiveBigIntegerField("tamaño (bytes)")
    # Archivo temporal: se borra al terminar el procesamiento o al eliminar la conversión.
    upload = models.FileField(
        "archivo subido", storage=_uploads_storage, upload_to=_upload_to, blank=True
    )
    status = models.CharField(
        "estado", max_length=20, choices=Status.choices, default=Status.PENDING
    )
    progress = models.PositiveSmallIntegerField("progreso (%)", default=0)
    # Mensaje para el usuario; nunca debe contener contenido del documento.
    error_message = models.CharField("mensaje de error", max_length=500, blank=True)
    # Resultado final ya anonimizado (Fases 2-6).
    markdown = models.TextField("Markdown anonimizado", blank=True)
    created_at = models.DateTimeField("creado", auto_now_add=True)
    updated_at = models.DateTimeField("actualizado", auto_now=True)
    completed_at = models.DateTimeField("completado", null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "conversión"
        verbose_name_plural = "conversiones"

    def __str__(self):
        return f"Conversión {self.id} ({self.get_file_type_display()})"

    @property
    def size_mb(self) -> float:
        return round(self.size_bytes / (1024 * 1024), 2)

    @property
    def is_finished(self) -> bool:
        return self.status in {self.Status.COMPLETED, self.Status.ERROR}

    def delete_upload(self) -> None:
        """Borra el archivo subido del disco (si existe) sin borrar el registro."""
        if self.upload and self.upload.name:
            storage = self.upload.storage
            if storage.exists(self.upload.name):
                storage.delete(self.upload.name)
            self.upload = ""

    def delete(self, *args, **kwargs):
        self.delete_upload()
        return super().delete(*args, **kwargs)

    @property
    def stem(self) -> str:
        """Nombre original sin extensión, para el archivo .md descargado."""
        return Path(self.original_filename).stem
