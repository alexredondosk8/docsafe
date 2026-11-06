"""Vistas de la app de documentos: subida, detalle, estado, descarga, historial y eliminación."""

import io
import logging

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.anonymization import ENTITY_LABELS_ES, EntityType, ReviewError, add_term, apply_review

from . import pipeline
from .forms import UploadForm
from .models import Conversion
from .tasks import enqueue_conversion

# Regla: no registrar nombres de archivo ni contenido (pueden tener datos personales).
logger = logging.getLogger(__name__)


@require_http_methods(["GET", "HEAD", "POST"])
def upload(request):
    """Pantalla principal: subir UN documento."""
    upload_error = None
    if request.method == "POST":
        uploaded_files = request.FILES.getlist("file")  # lee el cuerpo (y aplica el límite)
        if getattr(request, "upload_too_large", False):
            form = UploadForm()
            upload_error = (
                f"El archivo supera el tamaño máximo de {settings.MAX_UPLOAD_SIZE_MB} MB."
            )
        elif len(uploaded_files) > 1:
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
                try:
                    conversion.save()
                except Exception:
                    conversion.delete_upload()  # que no quede el documento huérfano en disco
                    raise
                enqueue_conversion(conversion.id)
                logger.info(
                    "Conversión %s creada: tipo=%s tamaño=%d bytes",
                    conversion.id,
                    conversion.file_type,
                    conversion.size_bytes,
                )
                messages.success(request, "Archivo recibido. El procesamiento ha comenzado.")
                return redirect("documents:detail", pk=conversion.id)
    else:
        form = UploadForm()
    return render(request, "documents/upload.html", {"form": form, "upload_error": upload_error})


def detail(request, pk):
    pipeline.expire_stale_reviews()
    conversion = get_object_or_404(Conversion, pk=pk)
    context = {"conversion": conversion}
    if conversion.in_review:
        review = pipeline.load_review(conversion)
        labels = review.labels()
        preview, _summary = apply_review(conversion.review_text, review)
        context.update(
            {
                "review_entities": [
                    {"entity": entity, "label": labels.get(entity.key, "")}
                    for entity in review.entities
                ],
                "review_preview": preview,
                "entity_types": [(t.value, ENTITY_LABELS_ES[t]) for t in EntityType],
                "review_expiry_hours": settings.REVIEW_EXPIRY_HOURS,
            }
        )
    response = render(request, "documents/detail.html", context)
    if conversion.in_review:
        # La página muestra datos reales: que el navegador no la guarde.
        response["Cache-Control"] = "no-store, private"
    return response


def _review_or_redirect(request, pk):
    conversion = get_object_or_404(Conversion, pk=pk)
    if not conversion.in_review:
        messages.error(request, "Esta conversión ya no está en revisión.")
        return conversion, redirect("documents:detail", pk=pk)
    return conversion, None


@require_POST
def review_update(request, pk):
    """Guarda las casillas marcadas; con accion=confirmar genera el Markdown final."""
    conversion, response = _review_or_redirect(request, pk)
    if response:
        return response
    review = pipeline.load_review(conversion)
    review.set_enabled(set(request.POST.getlist("entidad")))
    if request.POST.get("accion") == "confirmar":
        pipeline.confirm_review(conversion, review)
        messages.success(
            request,
            "Markdown anonimizado generado. Los datos originales se borraron de la aplicación.",
        )
        return redirect("documents:detail", pk=pk)
    pipeline.save_review(conversion, review)
    messages.info(request, "Vista previa actualizada con tu selección.")
    return redirect(reverse("documents:detail", args=[pk]) + "#vista-previa")


@require_POST
def review_add(request, pk):
    """Añade un texto que se escapó a la detección."""
    conversion, response = _review_or_redirect(request, pk)
    if response:
        return response
    try:
        entity_type = EntityType(request.POST.get("tipo", ""))
    except ValueError:
        messages.error(request, "Elige un tipo de dato válido.")
        return redirect("documents:detail", pk=pk)
    review = pipeline.load_review(conversion)
    try:
        entity = add_term(
            conversion.review_text, review, request.POST.get("valor", ""), entity_type
        )
    except ReviewError as exc:
        messages.error(request, str(exc))
        return redirect("documents:detail", pk=pk)
    pipeline.save_review(conversion, review)
    messages.success(
        request, f"Añadido: {entity.count} aparición(es) se reemplazarán como {entity.description}."
    )
    return redirect(reverse("documents:detail", args=[pk]) + "#revision")


@require_GET
def status(request, pk):
    """Estado para la consulta periódica del navegador. Nunca incluye contenido."""
    conversion = get_object_or_404(Conversion, pk=pk)
    response = JsonResponse(
        {
            "status": conversion.status,
            "status_display": conversion.get_status_display(),
            "progress": conversion.progress,
            "progress_message": conversion.progress_message,
            "is_active": conversion.is_active,
        }
    )
    response["Cache-Control"] = "no-store"
    return response


@require_GET
def download(request, pk):
    conversion = get_object_or_404(Conversion, pk=pk)
    if conversion.status != Conversion.Status.COMPLETED or not conversion.markdown:
        raise Http404("La conversión no está completada.")
    response = FileResponse(
        io.BytesIO(conversion.markdown.encode("utf-8")),
        as_attachment=True,
        filename=f"{conversion.stem}.md",
        content_type="text/markdown; charset=utf-8",
    )
    response["Cache-Control"] = "no-store"
    return response


def history(request):
    pipeline.expire_stale_reviews()
    page = Paginator(Conversion.objects.all(), 20).get_page(request.GET.get("pagina"))
    return render(request, "documents/history.html", {"page": page})


@require_POST
def delete(request, pk):
    conversion = get_object_or_404(Conversion, pk=pk)
    conversion.delete()
    logger.info("Conversión %s eliminada", pk)
    messages.success(request, "La conversión y su archivo se eliminaron.")
    return redirect("documents:history")
