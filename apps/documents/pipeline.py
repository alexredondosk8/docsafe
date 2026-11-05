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

from django.conf import settings
from django.utils import timezone

from apps.anonymization import ENTITY_LABELS_ES, Anonymizer, AnonymizerConfig, EntityType
from apps.conversion import ConversionError, convert

from .models import Conversion

logger = logging.getLogger(__name__)

# Capas de anonimización activas. "reglas" (Fase 4); la Fase 6 añade "llm".
# Con solo reglas, la interfaz advierte que nombres o direcciones en texto libre pueden escaparse.
ANONYMIZATION_LAYERS = ("reglas",)

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
        warnings = result.warnings

        _update(pk, status=Conversion.Status.ANONYMIZING, progress=50)
        markdown, replacements = anonymize(
            result.markdown, lambda pct: _update(pk, progress=50 + pct * 45 // 100)
        )
        del result  # el texto original no se conserva

        _update(
            pk,
            status=Conversion.Status.COMPLETED,
            progress=100,
            markdown=markdown,
            replacements=replacements,
            warnings=warnings,
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
        _update(
            pk,
            status=Conversion.Status.ERROR,
            error_message=message[:500],
            markdown="",
            replacements=[],
        )


def build_anonymizer() -> Anonymizer:
    config = AnonymizerConfig(
        disabled_types=frozenset(EntityType(t) for t in settings.ANONYMIZATION_DISABLED_TYPES),
        anonymize_all_dates=settings.ANONYMIZE_ALL_DATES,
    )
    return Anonymizer(config)


def anonymize(markdown: str, report_progress) -> tuple[str, list[dict]]:
    """Anonimiza el Markdown y devuelve (texto, resumen de reemplazos sin valores reales).

    Fase 4: reglas (regex y tablas). La Fase 6 añade el LLM y la fragmentación.
    """
    anonymizer = build_anonymizer()
    try:
        text = anonymizer.anonymize(markdown)
        summary = [
            {
                "type": entity.type.value,
                "description": ENTITY_LABELS_ES[entity.type],
                "label": entity.label,
                "count": entity.count,
            }
            for entity in anonymizer.entity_map.entities
        ]
    finally:
        anonymizer.entity_map.clear()  # los valores reales no salen de esta función
    report_progress(100)
    return text, summary
