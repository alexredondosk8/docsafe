"""Inicia DocSafe: aplica migraciones, arranca el procesador en segundo plano y el servidor web.

Uso:  uv run python manage.py iniciar [--puerto 8000]

El servidor siempre escucha solo en 127.0.0.1 (no es accesible desde otros equipos).
Si ya hay un procesador de DocSafe en marcha, no inicia otro: dos procesadores comparten la
misma cola y uno con código antiguo podría procesar documentos sin las reglas actuales.

Para desarrollo con recarga automática, usar dos terminales:
    uv run python manage.py runserver 127.0.0.1:8000
    uv run python manage.py qcluster
"""

import os
import socket
import subprocess
import sys
from pathlib import Path

import psutil
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from apps.documents.tasks import requeue_unfinished

HOST = "127.0.0.1"


def find_running_workers(base_dir: Path) -> list[int]:
    """PIDs de procesos `manage.py qcluster` de este proyecto que estén en marcha."""
    base = os.path.normcase(str(Path(base_dir).resolve()))
    pids = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmdline = proc.info["cmdline"] or []
            if "qcluster" not in cmdline or not any("manage.py" in a for a in cmdline):
                continue
            manage = next(a for a in cmdline if "manage.py" in a)
            path = Path(manage) if os.path.isabs(manage) else Path(proc.cwd()) / manage
            if os.path.normcase(str(path.resolve().parent)) == base:
                pids.append(proc.info["pid"])
        except (psutil.Error, OSError, StopIteration):
            continue
    return pids


def port_in_use(port: int) -> bool:
    """True si ya hay un servidor escuchando en 127.0.0.1:<port>.

    Necesario en Windows: el servidor de Django puede abrir un puerto ocupado sin avisar
    y las peticiones siguen llegando al servidor antiguo.
    """
    try:
        with socket.create_connection((HOST, port), timeout=0.5):
            return True
    except OSError:
        return False


class Command(BaseCommand):
    help = "Inicia el procesador en segundo plano y el servidor web local (127.0.0.1)."

    def add_arguments(self, parser):
        parser.add_argument("--puerto", type=int, default=8000, help="puerto (por defecto 8000)")

    def handle(self, *args, **options):
        port = options["puerto"]
        running = find_running_workers(settings.BASE_DIR)
        if running:
            raise CommandError(
                "Ya hay un procesador de DocSafe en marcha (PID "
                + ", ".join(map(str, running))
                + "). Ciérralo (Ctrl+C en su ventana) antes de iniciar otro."
            )
        if port_in_use(port):
            raise CommandError(
                f"El puerto {port} ya está en uso (¿quedó abierto otro servidor de DocSafe?). "
                "Ciérralo con Ctrl+C (o Ctrl+Pausa) en su ventana, o usa otro puerto: "
                "uv run python manage.py iniciar --puerto 8001"
            )

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
