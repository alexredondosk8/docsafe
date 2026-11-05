"""Inicia DocSafe: aplica migraciones, arranca el procesador en segundo plano y el servidor web.

Uso:  uv run python manage.py iniciar [--puerto 8000]

El servidor siempre escucha solo en 127.0.0.1 (no es accesible desde otros equipos).
Para desarrollo con recarga automática, usar dos terminales:
    uv run python manage.py runserver 127.0.0.1:8000
    uv run python manage.py qcluster
"""

import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand

from apps.documents.tasks import requeue_unfinished

HOST = "127.0.0.1"


class Command(BaseCommand):
    help = "Inicia el procesador en segundo plano y el servidor web local (127.0.0.1)."

    def add_arguments(self, parser):
        parser.add_argument("--puerto", type=int, default=8000, help="puerto (por defecto 8000)")

    def handle(self, *args, **options):
        port = options["puerto"]
        call_command("migrate", interactive=False, verbosity=0)
        pending = requeue_unfinished()
        if pending:
            self.stdout.write(f"Se reanudarán {pending} conversiones pendientes.")

        manage_py = Path(settings.BASE_DIR) / "manage.py"
        worker = subprocess.Popen([sys.executable, str(manage_py), "qcluster"])  # noqa: S603
        self.stdout.write(self.style.SUCCESS("Procesador en segundo plano iniciado."))
        self.stdout.write(
            self.style.SUCCESS(f"Abre http://{HOST}:{port} en tu navegador. Ctrl+C para salir.")
        )
        try:
            call_command("runserver", f"{HOST}:{port}", use_reloader=False)
        except KeyboardInterrupt:
            pass
        finally:
            self.stdout.write("Deteniendo el procesador en segundo plano…")
            worker.terminate()
            try:
                worker.wait(timeout=15)
            except subprocess.TimeoutExpired:
                worker.kill()
