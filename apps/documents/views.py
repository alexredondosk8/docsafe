"""Vistas de la app de documentos: subida, detalle, historial y eliminación."""

import logging

from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from .forms import UploadForm
from .models import Conversion

# Regla: no registrar nombres de archivo ni contenido (pueden tener datos personales).
logger = logging.getLogger(__name__)


@require_http_methods(["GET", "POST"])
def upload(request):
    """Pantalla principal: subir UN documento."""
    upload_error = None
    if request.method == "POST":
        if len(request.FILES.getlist("file")) > 1:
            form = UploadForm()
            upload_error = "Sube un solo archivo a la vez."
        else:
            form = UploadForm(request.POST, request.FILES)
            if form.is_valid():
                uploaded = form.cleaned_data["file"]
                conversion = Conversion(
                    original_filename=uploaded.name,
                    file_type=form.file_type,
                    size_bytes=uploaded.size,
                )
                conversion.upload.save(uploaded.name, uploaded, save=False)
                conversion.save()
                logger.info(
                    "Conversión %s creada: tipo=%s tamaño=%d bytes",
                    conversion.id,
                    conversion.file_type,
                    conversion.size_bytes,
                )
                messages.success(request, "Archivo recibido correctamente.")
                return redirect("documents:detail", pk=conversion.id)
    else:
        form = UploadForm()
    return render(request, "documents/upload.html", {"form": form, "upload_error": upload_error})


def detail(request, pk):
    conversion = get_object_or_404(Conversion, pk=pk)
    return render(request, "documents/detail.html", {"conversion": conversion})


def history(request):
    page = Paginator(Conversion.objects.all(), 20).get_page(request.GET.get("pagina"))
    return render(request, "documents/history.html", {"page": page})


@require_POST
def delete(request, pk):
    conversion = get_object_or_404(Conversion, pk=pk)
    conversion.delete()
    logger.info("Conversión %s eliminada", pk)
    messages.success(request, "La conversión y su archivo se eliminaron.")
    return redirect("documents:history")
