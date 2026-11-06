"""Sustituye la tarea periódica de caducidad por la de mantenimiento (caducidad + archivos huérfanos)."""

from django.db import migrations

OLD_NAME = "docsafe-caducar-revisiones"
OLD_FUNC = "apps.documents.tasks.expire_reviews"
NAME = "docsafe-mantenimiento"
FUNC = "apps.documents.tasks.maintenance"


def forwards(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.filter(name=OLD_NAME).delete()
    Schedule.objects.update_or_create(
        name=NAME,
        defaults={"func": FUNC, "schedule_type": "I", "minutes": 15, "repeats": -1},
    )


def backwards(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.filter(name=NAME).delete()
    Schedule.objects.update_or_create(
        name=OLD_NAME,
        defaults={"func": OLD_FUNC, "schedule_type": "I", "minutes": 15, "repeats": -1},
    )


class Migration(migrations.Migration):
    dependencies = [("documents", "0005_expire_reviews_schedule")]

    operations = [migrations.RunPython(forwards, backwards)]
