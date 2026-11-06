"""Manejador de subida que corta los archivos demasiado grandes mientras se reciben."""

from django.conf import settings
from django.core.files.uploadhandler import FileUploadHandler, StopUpload


class SizeLimitUploadHandler(FileUploadHandler):
    """Detiene la recepción en cuanto el archivo supera DOCSAFE_MAX_UPLOAD_MB.

    Va primero en FILE_UPLOAD_HANDLERS: lo que sobra no llega a escribirse en disco y Django
    borra el temporal parcial. Marca `request.upload_too_large` para que la vista lo explique.
    """

    def receive_data_chunk(self, raw_data, start):
        if start + len(raw_data) > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
            self.request.upload_too_large = True
            raise StopUpload(connection_reset=False)
        return raw_data

    def file_complete(self, file_size):
        return None
