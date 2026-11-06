"""Tareas en segundo plano (django-q2)."""

import logging

from django.db import transaction
from django_q.tasks import async_task

from . import pipeline

logger = logging.getLogger(__name__)

TASK_PATH = "apps.documents.tasks.process_conversion"
# Tarea periódica (la crea la migración 0005): descarta revisiones caducadas aunque nadie
# abra el detalle ni el historial.
EXPIRE_REVIEWS_PATH = "apps.documents.tasks.expire_reviews"


def process_conversion(conversion_id: str) -> None:
    """Punto de entrada de la tarea. Recibe solo el id; no devuelve nada."""
    pipeline.process(conversion_id)


def expire_reviews() -> None:
    """Tarea periódica: borra los datos originales de las revisiones caducadas.

    Captura cualquier error para que django-q no guarde trazas; no devuelve nada.
    """
    try:
        pipeline.expire_stale_reviews()
    except Exception as exc:  # noqa: BLE001
        logger.error("Error al caducar revisiones (%s)", type(exc).__name__)


def requeue_unfinished() -> int:
    """Vuelve a encolar las conversiones sin terminar (p. ej. si el procesador estaba apagado).

    Encolar dos veces la misma conversión no causa problemas: la segunda ejecución ve que
    ya terminó y no hace nada.
    """
    from .models import Conversion

    active = [
        Conversion.Status.PENDING,
        Conversion.Status.CONVERTING,
        Conversion.Status.ANONYMIZING,
    ]
    ids = list(Conversion.objects.filter(status__in=active).values_list("id", flat=True))
    for conversion_id in ids:
        async_task(TASK_PATH, str(conversion_id), task_name=f"conversion-{conversion_id}")
    return len(ids)


def enqueue_conversion(conversion_id) -> None:
    """Encola el procesamiento cuando la transacción actual se confirme."""
    transaction.on_commit(
        lambda: async_task(TASK_PATH, str(conversion_id), task_name=f"conversion-{conversion_id}")
    )
