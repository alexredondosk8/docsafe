"""Flujo completo en el navegador: subir → revisar → confirmar → descargar."""

import re
from pathlib import Path

import pytest
from playwright.sync_api import expect

from apps.documents.models import Conversion

from .conftest import FIXTURES

pytestmark = pytest.mark.django_db(transaction=True)


def upload(page, live_server, name="contrato.pdf"):
    page.goto(live_server.url + "/")
    page.set_input_files("input[type=file]", FIXTURES / name)
    page.get_by_role("button", name="Subir").click()


def test_flujo_completo_con_revision_y_descarga(page, live_server, fake_ai, console_errors):
    upload(page, live_server)
    expect(page.get_by_text("Reemplazos detectados")).to_be_visible()

    # El usuario desmarca un falso positivo de la IA y añade un dato que se escapó.
    page.get_by_label("Reemplazar Bogotá").uncheck()
    page.get_by_role("button", name="Actualizar vista previa").click()
    expect(page.get_by_text("Vista previa actualizada")).to_be_visible()
    page.get_by_label("Texto tal como aparece en el documento").fill("consultoría")
    page.get_by_label("Tipo de dato").select_option(label="Nombre de empresa")
    page.get_by_role("button", name="Añadir").click()
    expect(page.get_by_text("Añadido: 1 aparición(es)")).to_be_visible()

    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.accept()))
    page.get_by_role("button", name="Confirmar y generar Markdown").click()
    expect(page.get_by_text("Markdown anonimizado generado")).to_be_visible()
    assert dialogs and "Generar el Markdown" in dialogs[0]

    with page.expect_download() as info:
        page.get_by_role("link", name="Descargar .md").click()
    download = info.value
    assert download.suggested_filename == "contrato.md"
    markdown = Path(download.path()).read_text(encoding="utf-8")

    for real in ["Juan", "María", "52.345.678", "Soluciones Andinas", "consultoría"]:
        assert real not in markdown
    assert "[NOMBRE_1]" in markdown and "[EMPRESA_2]" in markdown
    assert "Bogotá" in markdown  # desmarcado por el usuario

    conversion = Conversion.objects.get()
    assert conversion.review_text == "" and conversion.review_data == {}
    assert console_errors == []


def test_cancelar_el_aviso_no_confirma(page, live_server, fake_ai):
    upload(page, live_server)
    page.on("dialog", lambda d: d.dismiss())
    page.get_by_role("button", name="Confirmar y generar Markdown").click()

    expect(page.get_by_text("Reemplazos detectados")).to_be_visible()
    assert Conversion.objects.get().status == Conversion.Status.REVIEW


def test_eliminar_desde_el_historial(page, live_server, fake_ai):
    upload(page, live_server)
    page.get_by_role("link", name="Historial", exact=True).click()
    page.on("dialog", lambda d: d.accept())
    page.get_by_role("button", name="Eliminar").click()

    expect(page.get_by_text("La conversión y su archivo se eliminaron")).to_be_visible()
    assert not Conversion.objects.exists()


def test_el_navegador_rechaza_formatos_no_permitidos(page, live_server, tmp_path):
    texto = tmp_path / "notas.txt"
    texto.write_text("hola")
    page.goto(live_server.url + "/")
    page.set_input_files("input[type=file]", texto)

    expect(page.get_by_text("Formato no permitido")).to_be_visible()
    page.get_by_role("button", name="Subir").click()
    assert page.url == live_server.url + "/"
    assert not Conversion.objects.exists()


def test_el_estado_se_actualiza_solo(page, live_server):
    conversion = Conversion.objects.create(
        original_filename="a.pdf",
        file_type="pdf",
        size_bytes=1,
        status=Conversion.Status.ANONYMIZING,
        progress=50,
        progress_message="Analizando con IA: fragmento 1 de 2",
    )
    page.goto(f"{live_server.url}/conversiones/{conversion.id}/")
    expect(page.get_by_text("Analizando con IA: fragmento 1 de 2")).to_be_visible()

    # El procesador termina mientras la página está abierta: la página se recarga sola.
    Conversion.objects.filter(pk=conversion.pk).update(
        status=Conversion.Status.COMPLETED, progress=100, markdown="Hola [NOMBRE_1]"
    )
    expect(page.get_by_role("link", name="Descargar .md")).to_be_visible(timeout=10_000)
    expect(page.locator("#progress-bar")).to_have_attribute("style", re.compile("100%"))


def test_paginas_sin_errores_de_consola_ni_csp(page, live_server, console_errors):
    for path in ["/", "/historial/", "/configuracion/"]:
        page.goto(live_server.url + path)
    assert console_errors == []
