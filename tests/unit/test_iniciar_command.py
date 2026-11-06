"""Pruebas del comando `manage.py iniciar`."""

import pytest
from django.core.management import CommandError, call_command

from apps.documents.management.commands import iniciar


class FakeProcess:
    def __init__(self, args):
        self.args = args
        self.terminated = False

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0


@pytest.fixture
def fake(monkeypatch):
    calls = {"commands": [], "process": None}

    def fake_popen(args):
        calls["process"] = FakeProcess(args)
        return calls["process"]

    def fake_call_command(name, *args, **kwargs):
        calls["commands"].append((name, args, kwargs))
        if name == "runserver":
            raise KeyboardInterrupt

    monkeypatch.setattr(iniciar.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(iniciar, "call_command", fake_call_command)
    monkeypatch.setattr(iniciar, "requeue_unfinished", lambda: 2)
    monkeypatch.setattr(iniciar, "find_running_workers", lambda base: [])
    monkeypatch.setattr(iniciar, "port_in_use", lambda port: False)
    monkeypatch.setattr(iniciar, "stop_process_tree", lambda process: process.terminate())
    return calls


def test_inicia_procesador_y_servidor_local(fake, capsys):
    call_command("iniciar")
    assert "Se reanudarán 2 conversiones pendientes" in capsys.readouterr().out

    names = [c[0] for c in fake["commands"]]
    assert names == ["migrate", "runserver"]
    assert fake["commands"][1][1] == ("127.0.0.1:8000",)
    assert fake["commands"][1][2] == {"use_reloader": False}
    assert fake["process"].args[-1] == "qcluster"
    assert fake["process"].terminated


def test_puerto_personalizado(fake):
    call_command("iniciar", "--puerto", "8050")
    assert fake["commands"][1][1] == ("127.0.0.1:8050",)


def test_no_inicia_si_ya_hay_un_procesador(fake, monkeypatch):
    monkeypatch.setattr(iniciar, "find_running_workers", lambda base: [1234])
    with pytest.raises(CommandError, match="Ya hay un procesador de DocSafe en marcha"):
        call_command("iniciar")
    assert fake["commands"] == []
    assert fake["process"] is None


def test_no_inicia_si_el_puerto_esta_ocupado(fake, monkeypatch):
    monkeypatch.setattr(iniciar, "port_in_use", lambda port: port == 8000)
    with pytest.raises(CommandError, match="El puerto 8000 ya está en uso"):
        call_command("iniciar")
    assert fake["process"] is None  # no deja un procesador huérfano


def test_port_in_use_detecta_un_servidor_real():
    import socket

    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        assert iniciar.port_in_use(port)
    assert not iniciar.port_in_use(port)


class FakeProc:
    def __init__(self, pid, cmdline, cwd, ppid=None, environ=None):
        self.info = {"pid": pid, "ppid": ppid, "cmdline": cmdline}
        self._cwd = cwd
        self._environ = environ if environ is not None else {}

    def cwd(self):
        return self._cwd

    def environ(self):
        if self._environ == "denied":
            raise iniciar.psutil.AccessDenied(self.info["pid"])
        return self._environ


def test_detecta_procesadores_solo_de_este_proyecto(monkeypatch, tmp_path):
    project = tmp_path / "docsafe"
    other = tmp_path / "otro"
    project.mkdir()
    other.mkdir()
    procs = [
        FakeProc(1, ["python", str(project / "manage.py"), "qcluster"], str(tmp_path)),
        FakeProc(2, ["python", "manage.py", "qcluster"], str(project)),
        FakeProc(3, ["python", str(other / "manage.py"), "qcluster"], str(other)),
        FakeProc(4, ["python", "manage.py", "runserver"], str(project)),
        FakeProc(5, None, str(project)),
    ]
    monkeypatch.setattr(iniciar.psutil, "process_iter", lambda attrs: procs)
    assert iniciar.find_running_workers(project) == [1, 2]


FORK = ["python", "-c", "from multiprocessing.spawn import spawn_main", "--multiprocessing-fork"]
DJANGO_ENV = {"DJANGO_SETTINGS_MODULE": "config.settings"}


def test_detecta_procesador_huerfano(monkeypatch, tmp_path):
    """Hijos de un qcluster cuyo proceso principal ya se cerró (ocurrió en la Fase 6)."""
    project = tmp_path / "docsafe"
    project.mkdir()
    procs = [
        # Guardián huérfano (su padre ya no existe) y sus hijos.
        FakeProc(10, FORK, str(project), ppid=999, environ=DJANGO_ENV),
        FakeProc(11, FORK, str(project), ppid=10, environ=DJANGO_ENV),
        FakeProc(12, FORK, str(project), ppid=10, environ=DJANGO_ENV),
    ]
    monkeypatch.setattr(iniciar.psutil, "process_iter", lambda attrs: procs)
    assert iniciar.find_running_workers(project) == [10]


def test_procesador_vivo_se_informa_una_vez(monkeypatch, tmp_path):
    project = tmp_path / "docsafe"
    project.mkdir()
    procs = [
        FakeProc(20, ["python", "manage.py", "qcluster"], str(project), ppid=1),
        FakeProc(21, ["python", "manage.py", "qcluster"], str(project), ppid=20),
        FakeProc(22, FORK, str(project), ppid=21, environ=DJANGO_ENV),
    ]
    monkeypatch.setattr(iniciar.psutil, "process_iter", lambda attrs: procs)
    assert iniciar.find_running_workers(project) == [20]


def test_ignora_multiprocessing_ajeno(monkeypatch, tmp_path):
    project = tmp_path / "docsafe"
    other = tmp_path / "otro"
    project.mkdir()
    other.mkdir()
    procs = [
        FakeProc(30, FORK, str(other), environ=DJANGO_ENV),  # otro proyecto
        FakeProc(31, FORK, str(project), environ={}),  # no es Django
        FakeProc(32, FORK, str(project), environ="denied"),  # sin permiso para leerlo
    ]
    monkeypatch.setattr(iniciar.psutil, "process_iter", lambda attrs: procs)
    assert iniciar.find_running_workers(project) == []


def test_mensaje_explica_como_cerrar_un_huerfano(fake, monkeypatch):
    monkeypatch.setattr(iniciar, "find_running_workers", lambda base: [18640])
    monkeypatch.setattr(iniciar.sys, "platform", "win32")
    with pytest.raises(CommandError, match=r"taskkill /PID 18640 /T /F"):
        call_command("iniciar")


def test_stop_process_tree_cierra_tambien_los_hijos():
    """Un padre que lanza un hijo: al detenerlo no debe quedar ningún huérfano."""
    import subprocess
    import sys
    import time

    import psutil

    child_code = "import time; time.sleep(60)"
    parent_code = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}]); time.sleep(60)"
    )
    # Intérprete base, como los hijos de multiprocessing: con el lanzador de .venv, Windows
    # cerraría al hijo por su cuenta y la prueba no detectaría el fallo.
    python = getattr(sys, "_base_executable", sys.executable)
    parent = subprocess.Popen([python, "-c", parent_code])  # noqa: S603
    try:
        root = psutil.Process(parent.pid)
        for _ in range(100):  # hasta 5 s
            if root.children():
                break
            time.sleep(0.05)
        children = root.children(recursive=True)
        assert children, "el proceso hijo no llegó a arrancar"

        iniciar.stop_process_tree(parent, grace=0.2)

        assert parent.poll() is not None
        assert not any(c.is_running() and c.status() != psutil.STATUS_ZOMBIE for c in children)
    finally:
        for proc in [psutil.Process(parent.pid)] if parent.poll() is None else []:
            proc.kill()
        for child in locals().get("children", []):
            if child.is_running():
                child.kill()
