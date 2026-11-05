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
    def __init__(self, pid, cmdline, cwd):
        self.info = {"pid": pid, "cmdline": cmdline}
        self._cwd = cwd

    def cwd(self):
        return self._cwd


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
