"""Pruebas del comando `manage.py iniciar`."""

import pytest
from django.core.management import call_command

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
