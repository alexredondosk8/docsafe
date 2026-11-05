"""Tareas en segundo plano (django-q2)."""

from django.db import transaction
from django_q.tasks import async_task

from . import pipeline

TASK_PATH = "apps.documents.tasks.process_conversion"


def process_conversion(conversion_id: str) -> None:
    """Punto de entrada de la tarea. Recibe solo el id; no devuelve nada."""
    pipeline.process(conversion_id)


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
