"""Inicia DocSafe: aplica migraciones, arranca el procesador en segundo plano y el servidor web.

Uso:  uv run python manage.py iniciar [--puerto 8000]

El servidor siempre escucha solo en 127.0.0.1 (no es accesible desde otros equipos).
Si ya hay un procesador de DocSafe en marcha, no inicia otro: dos procesadores comparten la
misma cola y uno con código antiguo podría procesar documentos sin las reglas actuales.

Para desarrollo con recarga automática, usar dos terminales:
    uv run python manage.py runserver 127.0.0.1:8000
    uv run python manage.py qcluster
"""

import contextlib
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


def _same_dir(path, base: str) -> bool:
    return os.path.normcase(str(Path(path).resolve())) == base


def _is_project_worker(proc, base: str) -> bool:
    """True si el proceso es un procesador (qcluster) de este proyecto o uno de sus hijos."""
    cmdline = proc.info["cmdline"] or []
    if "qcluster" in cmdline and any("manage.py" in a for a in cmdline):
        manage = next(a for a in cmdline if "manage.py" in a)
        path = Path(manage) if os.path.isabs(manage) else Path(proc.cwd()) / manage
        return _same_dir(path.parent, base)
    if "--multiprocessing-fork" in cmdline:
        # Hijos del procesador (guardián, worker, monitor…). Si el proceso principal se cerró
        # sin detenerlos, quedan huérfanos, siguen atendiendo la cola con el código antiguo y
        # su línea de órdenes ya no menciona manage.py: se reconocen por su carpeta y entorno.
        return _same_dir(proc.cwd(), base) and "DJANGO_SETTINGS_MODULE" in proc.environ()
    return False


def find_running_workers(base_dir: Path) -> list[int]:
    """PIDs de los procesadores de este proyecto en marcha, incluidos los huérfanos.

    Solo devuelve los procesos raíz: sus hijos se cierran con ellos.
    """
    base = os.path.normcase(str(Path(base_dir).resolve()))
    found: dict[int, int | None] = {}
    for proc in psutil.process_iter(["pid", "ppid", "cmdline"]):
        try:
            if _is_project_worker(proc, base):
                found[proc.info["pid"]] = proc.info.get("ppid")
        except (psutil.Error, OSError, StopIteration):
            continue
    return sorted(pid for pid, ppid in found.items() if ppid not in found)


def stop_command(pids: list[int]) -> str:
    """Orden para cerrar a mano los procesadores (y sus hijos) que no tienen ventana."""
    if sys.platform == "win32":
        return " ; ".join(f"taskkill /PID {pid} /T /F" for pid in pids)
    return "kill " + " ".join(map(str, pids))


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


def stop_process_tree(process, grace: float = 10) -> None:
    """Detiene el procesador y TODOS sus procesos hijos.

    Cerrar solo el proceso lanzado no basta: en Windows es el lanzador de `.venv` y, si muere
    antes de que qcluster cierre a sus hijos, el guardián y los workers quedan huérfanos y
    siguen atendiendo la cola con el código antiguo (ocurrió en la Fase 6).
    Primero espera `grace` segundos a que se cierre solo (Ctrl+C también le llega) y luego
    termina a la fuerza lo que quede.
    """
    try:
        root = psutil.Process(process.pid)
        tree = [root, *root.children(recursive=True)]
    except psutil.Error:
        tree = []
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=grace)
    # Hijos creados después (p. ej. workers reiniciados) también se incluyen.
    for proc in list(tree):
        try:
            tree.extend(c for c in proc.children(recursive=True) if c not in tree)
        except psutil.Error:
            continue
    for proc in tree:
        try:
            proc.terminate()
        except psutil.Error:
            continue
    _, alive = psutil.wait_procs(tree, timeout=5)
    for proc in alive:
        try:
            proc.kill()
        except psutil.Error:
            continue


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
                + "). Ciérralo con Ctrl+C en su ventana antes de iniciar otro. Si no tiene "
                "ventana (quedó abierto de una ejecución anterior), ciérralo con: "
                + stop_command(running)
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
            stop_process_tree(worker)
