"""Programa la caducidad de revisiones como tarea periódica de django-q (cada 15 minutos)."""

from django.db import migrations

SCHEDULE_NAME = "docsafe-caducar-revisiones"
FUNC = "apps.documents.tasks.expire_reviews"


def create_schedule(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.update_or_create(
        name=SCHEDULE_NAME,
        defaults={"func": FUNC, "schedule_type": "I", "minutes": 15, "repeats": -1},
    )


def delete_schedule(apps, schema_editor):
    apps.get_model("django_q", "Schedule").objects.filter(name=SCHEDULE_NAME).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0004_review_and_llm_status"),
        ("django_q", "0019_alter_task_options_alter_ormq_key_alter_ormq_lock_and_more"),
    ]

    operations = [migrations.RunPython(create_schedule, delete_schedule)]
