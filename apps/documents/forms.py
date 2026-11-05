"""Formularios de la app de documentos."""

from django import forms
from django.conf import settings

from .validation import ALLOWED_EXTENSIONS, InvalidFileError, clean_filename, validate_upload


class UploadForm(forms.Form):
    file = forms.FileField(
        label="Documento",
        help_text="PDF con texto, Word (.docx) o Excel (.xlsx). Un archivo a la vez.",
        error_messages={"required": "Selecciona un archivo.", "empty": "El archivo está vacío."},
        widget=forms.ClearableFileInput(
            attrs={
                "class": "form-control",
                "accept": ",".join(f".{e}" for e in ALLOWED_EXTENSIONS),
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        self.fields["file"].widget.attrs["data-max-bytes"] = str(self.max_bytes)
        self.file_type = None

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        try:
            self.file_type = validate_upload(uploaded.name, uploaded.size, uploaded, self.max_bytes)
        except InvalidFileError as exc:
            raise forms.ValidationError(str(exc)) from None
        uploaded.name = clean_filename(uploaded.name)
        return uploaded
