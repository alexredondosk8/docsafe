"""Flujo de procesamiento de una conversión: convertir → anonimizar → completar.

Se ejecuta en el procesador en segundo plano (django-q2). Reglas:
- Los cambios de estado se hacen con ``UPDATE`` por id: si el usuario elimina la conversión
  mientras se procesa, la tarea se detiene sin volver a crear el registro.
- El archivo subido se borra siempre al terminar (con éxito o con error).
- Los logs nunca incluyen contenido, nombres de archivo ni mensajes de excepciones de
  terceros (podrían contener texto del documento): solo id y tipo de error.
"""

import contextlib
import logging
from pathlib import Path

from django.utils import timezone

from apps.conversion import ConversionError, convert

from .models import Conversion

logger = logging.getLogger(__name__)

# Pasa a True cuando exista la capa de anonimización (Fases 4-6). Mientras sea False, la
# interfaz advierte que el Markdown contiene los datos originales.
ANONYMIZATION_ENABLED = False

GENERIC_ERROR = (
    "Ocurrió un error inesperado al procesar el documento. "
    "Intenta de nuevo; si persiste, revisa el archivo."
)


class Cancelled(Exception):
    """La conversión se eliminó mientras se procesaba."""


def _update(pk, **fields) -> None:
    fields.setdefault("updated_at", timezone.now())
    if not Conversion.objects.filter(pk=pk).update(**fields):
        raise Cancelled


def process(conversion_id) -> None:
    """Procesa una conversión pendiente. Nunca lanza excepciones."""
    try:
        conversion = Conversion.objects.get(pk=conversion_id)
    except Conversion.DoesNotExist:
        logger.info("Conversión %s ya no existe; se omite", conversion_id)
        return
    if conversion.is_finished:
        logger.info("Conversión %s ya estaba terminada; se omite", conversion_id)
        return

    pk = conversion.pk
    try:
        if not conversion.upload or not conversion.upload.name:
            raise ConversionError("El archivo subido ya no está disponible. Súbelo de nuevo.")
        path = Path(conversion.upload.path)
        if not path.exists():
            raise ConversionError("El archivo subido ya no está disponible. Súbelo de nuevo.")

        logger.info("Conversión %s: convirtiendo (%s)", pk, conversion.file_type)
        _update(pk, status=Conversion.Status.CONVERTING, progress=10, error_message="")
        result = convert(path, conversion.file_type)

        _update(pk, status=Conversion.Status.ANONYMIZING, progress=50)
        markdown = anonymize(
            result.markdown, lambda pct: _update(pk, progress=50 + pct * 45 // 100)
        )

        _update(
            pk,
            status=Conversion.Status.COMPLETED,
            progress=100,
            markdown=markdown,
            warnings=result.warnings,
            completed_at=timezone.now(),
        )
        logger.info("Conversión %s completada", pk)
    except Cancelled:
        logger.info("Conversión %s eliminada durante el procesamiento", pk)
    except ConversionError as exc:
        logger.info("Conversión %s no se pudo convertir", pk)
        _set_error(pk, str(exc))
    except Exception as exc:  # noqa: BLE001 - la tarea nunca debe fallar hacia django-q
        logger.error("Conversión %s: error inesperado (%s)", pk, type(exc).__name__)
        _set_error(pk, GENERIC_ERROR)
    finally:
        conversion.delete_upload()
        Conversion.objects.filter(pk=pk).update(upload="")


def _set_error(pk, message: str) -> None:
    with contextlib.suppress(Cancelled):
        _update(pk, status=Conversion.Status.ERROR, error_message=message[:500], markdown="")


def anonymize(markdown: str, report_progress) -> str:
    """Capa de anonimización. Se implementa en las Fases 4 (regex) y 6 (LLM)."""
    report_progress(100)
    return markdown
