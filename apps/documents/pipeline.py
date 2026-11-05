"""Flujo de procesamiento: convertir → detectar (reglas + IA) → revisión → completar.

Se ejecuta en el procesador en segundo plano (django-q2). Reglas:
- Los cambios de estado se hacen con ``UPDATE`` por id: si el usuario elimina la conversión
  mientras se procesa, la tarea se detiene sin volver a crear el registro.
- El archivo subido se borra siempre al terminar el análisis (con éxito o con error).
- El texto original y los valores reales se guardan SOLO mientras la conversión está
  «En revisión» y se borran al confirmar, al eliminar o al caducar la revisión.
- Los logs nunca incluyen contenido, nombres de archivo ni mensajes de excepciones de
  terceros (podrían contener texto del documento): solo id y tipo de error.
"""

import contextlib
import logging
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from apps.anonymization import (
    LLM_TYPES,
    Anonymizer,
    AnonymizerConfig,
    EntityType,
    LLMDetector,
    ReviewData,
    apply_review,
    build_review,
)
from apps.conversion import ConversionError, convert
from apps.llm.client import LLMConfig, get_provider

from .models import Conversion

logger = logging.getLogger(__name__)

GENERIC_ERROR = (
    "Ocurrió un error inesperado al procesar el documento. "
    "Intenta de nuevo; si persiste, revisa el archivo."
)
EXPIRED_MESSAGE = (
    "La revisión caducó sin confirmarse y los datos originales se borraron por seguridad. "
    "Sube el documento de nuevo."
)

# Progreso: conversión 10-40 %, reglas 45 %, IA 50-95 %, revisión lista 100 %.
_LLM_START, _LLM_END = 50, 95


class Cancelled(Exception):
    """La conversión se eliminó mientras se procesaba."""


def _update(pk, **fields) -> None:
    fields.setdefault("updated_at", timezone.now())
    if not Conversion.objects.filter(pk=pk).update(**fields):
        raise Cancelled


# --- Análisis en segundo plano ----------------------------------------------------------


def process(conversion_id) -> None:
    """Analiza una conversión pendiente y la deja «En revisión». Nunca lanza excepciones."""
    try:
        conversion = Conversion.objects.get(pk=conversion_id)
    except Conversion.DoesNotExist:
        logger.info("Conversión %s ya no existe; se omite", conversion_id)
        return
    if conversion.is_finished or conversion.in_review:
        logger.info("Conversión %s ya estaba analizada; se omite", conversion_id)
        return

    pk = conversion.pk
    try:
        if not conversion.upload or not conversion.upload.name:
            raise ConversionError("El archivo subido ya no está disponible. Súbelo de nuevo.")
        path = Path(conversion.upload.path)
        if not path.exists():
            raise ConversionError("El archivo subido ya no está disponible. Súbelo de nuevo.")

        logger.info("Conversión %s: convirtiendo (%s)", pk, conversion.file_type)
        _update(
            pk,
            status=Conversion.Status.CONVERTING,
            progress=10,
            progress_message="Convirtiendo a Markdown",
            error_message="",
        )
        result = convert(path, conversion.file_type)
        text, warnings = result.markdown, list(result.warnings)
        del result

        _update(
            pk,
            status=Conversion.Status.ANONYMIZING,
            progress=45,
            progress_message="Buscando datos personales con reglas",
        )
        review, llm_status, llm_warnings = analyze(text, pk)

        _update(
            pk,
            status=Conversion.Status.REVIEW,
            progress=100,
            progress_message="",
            review_text=text,
            review_data=review.to_dict(),
            warnings=warnings + llm_warnings,
            llm_status=llm_status,
        )
        logger.info("Conversión %s lista para revisión (IA: %s)", pk, llm_status or "sin usar")
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


def analyze(text: str, pk=None) -> tuple[ReviewData, str, list[str]]:
    """Detecta datos con reglas y, si está activa, con IA.

    Devuelve (revisión, estado de la IA, avisos para el usuario).
    """
    config = AnonymizerConfig(
        disabled_types=frozenset(EntityType(t) for t in settings.ANONYMIZATION_DISABLED_TYPES),
        anonymize_all_dates=settings.ANONYMIZE_ALL_DATES,
    )
    detector, llm_status, warnings = _build_llm_detector(config, pk)
    anonymizer = Anonymizer(config, extra_detectors=[detector] if detector else [])
    spans = anonymizer.find_spans(text)

    if detector is not None:
        stats = detector.stats
        llm_status = {
            "completo": Conversion.LLMStatus.COMPLETE,
            "parcial": Conversion.LLMStatus.PARTIAL,
            "fallido": Conversion.LLMStatus.FAILED,
        }[stats.status]
        if stats.aborted and not stats.chunks_ok:
            warnings.append(
                "La IA no estaba disponible y solo se aplicaron las reglas. "
                f"Motivo: {stats.abort_reason} Revisa el resultado con cuidado."
            )
        elif stats.chunks_failed:
            warnings.append(
                f"La IA no pudo analizar {stats.chunks_failed} de {stats.chunks_total} "
                "fragmentos del documento; en esas partes solo se aplicaron las reglas."
            )
    return build_review(text, spans), llm_status, warnings


def _build_llm_detector(config: AnonymizerConfig, pk):
    if not settings.LLM_ANONYMIZATION_ENABLED:
        return (
            None,
            Conversion.LLMStatus.DISABLED,
            [
                "La detección con IA está desactivada (DOCSAFE_USAR_IA=False): "
                "solo se usaron reglas."
            ],
        )
    llm_config = LLMConfig.from_settings()
    errors = llm_config.validation_errors()
    if errors:
        return (
            None,
            Conversion.LLMStatus.NOT_CONFIGURED,
            ["La IA no está configurada y solo se aplicaron las reglas: " + " ".join(errors)],
        )

    provider = get_provider()
    types = [t for t in LLM_TYPES if t not in config.disabled_types]
    if config.anonymize_all_dates:
        types.append(EntityType.FECHA)

    def on_progress(done: int, total: int) -> None:
        if pk is None or not total:
            return
        progress = _LLM_START + (_LLM_END - _LLM_START) * done // total
        message = (
            f"Analizando con IA: fragmento {min(done + 1, total)} de {total}"
            if done < total
            else "Preparando la revisión"
        )
        _update(pk, progress=progress, progress_message=message)

    detector = LLMDetector(
        provider.chat_json,
        chunk_chars=settings.LLM_CHUNK_CHARS,
        types=types,
        on_progress=on_progress,
    )
    return detector, Conversion.LLMStatus.NOT_USED, []


def _set_error(pk, message: str) -> None:
    with contextlib.suppress(Cancelled):
        _update(
            pk,
            status=Conversion.Status.ERROR,
            error_message=message[:500],
            progress_message="",
            markdown="",
            replacements=[],
            review_text="",
            review_data={},
        )


# --- Revisión (acciones del usuario) ----------------------------------------------------


def load_review(conversion: Conversion) -> ReviewData:
    return ReviewData.from_dict(conversion.review_data or {})


def save_review(conversion: Conversion, review: ReviewData) -> None:
    _update(conversion.pk, review_data=review.to_dict())


def confirm_review(conversion: Conversion, review: ReviewData) -> None:
    """Genera el Markdown final y borra el texto original y los valores reales."""
    markdown, summary = apply_review(conversion.review_text, review)
    _update(
        conversion.pk,
        status=Conversion.Status.COMPLETED,
        markdown=markdown,
        replacements=summary,
        review_text="",
        review_data={},
        completed_at=timezone.now(),
    )
    logger.info("Conversión %s confirmada (%d reemplazos)", conversion.pk, len(summary))


def expire_stale_reviews() -> int:
    """Descarta revisiones sin confirmar más antiguas que REVIEW_EXPIRY_HOURS."""
    limit = timezone.now() - timedelta(hours=settings.REVIEW_EXPIRY_HOURS)
    count = Conversion.objects.filter(status=Conversion.Status.REVIEW, updated_at__lt=limit).update(
        status=Conversion.Status.ERROR,
        error_message=EXPIRED_MESSAGE,
        review_text="",
        review_data={},
        markdown="",
        replacements=[],
        updated_at=timezone.now(),
    )
    if count:
        logger.info("%d revisiones caducadas: datos originales borrados", count)
    return count
