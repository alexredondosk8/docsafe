"""Pruebas de la revisión: agrupación, variantes, desmarcar, añadir y aplicar."""

import pytest

from apps.anonymization import (
    Anonymizer,
    EntityType,
    ReviewData,
    ReviewError,
    add_term,
    apply_review,
    build_review,
)
from apps.anonymization.entities import Span

T = EntityType


def review_of(text, *spans):
    return build_review(text, list(spans))


def span(text, value, entity_type, source="reglas", nth=0):
    start = -1
    for _ in range(nth + 1):
        start = text.index(value, start + 1)
    return Span(start, start + len(value), entity_type, 0, source)


def test_agrupa_por_entidad_y_cuenta_apariciones():
    text = "ana@x.co y ANA@X.CO; luis@x.co"
    review = build_review(text, Anonymizer().find_spans(text))
    assert [(e.type, e.values, e.count) for e in review.entities] == [
        (T.CORREO, ["ana@x.co", "ANA@X.CO"], 2),
        (T.CORREO, ["luis@x.co"], 1),
    ]


def test_une_variantes_de_un_nombre():
    text = "Juan Carlos Pérez Gómez firma. Luego Juan Pérez aprueba."
    review = review_of(
        text,
        span(text, "Juan Carlos Pérez Gómez", T.NOMBRE),
        span(text, "Juan Pérez", T.NOMBRE, "ia"),
    )
    assert len(review.entities) == 1
    entity = review.entities[0]
    assert entity.values == ["Juan Carlos Pérez Gómez", "Juan Pérez"]
    assert entity.count == 2
    assert entity.sources == ["reglas", "ia"]
    out, _ = apply_review(text, review)
    assert out == "[NOMBRE_1] firma. Luego [NOMBRE_1] aprueba."


def test_no_une_variantes_ambiguas():
    text = "Juan Pérez Gómez y Juan Pérez Ruiz. Juan Pérez llegó."
    review = review_of(
        text,
        span(text, "Juan Pérez Gómez", T.NOMBRE),
        span(text, "Juan Pérez Ruiz", T.NOMBRE),
        span(text, "Juan Pérez", T.NOMBRE, nth=2),
    )
    assert len(review.entities) == 3


def test_une_mencion_parcial_si_es_de_una_sola_persona():
    """Visto con qwen3:8b real: "Gloria comentó…" tras "Gloria Restrepo"."""
    text = "Visitamos a Gloria Restrepo. Gloria comentó algo. Restrepo firmó."
    review = review_of(
        text,
        span(text, "Gloria Restrepo", T.NOMBRE),
        span(text, "Gloria", T.NOMBRE, "ia", nth=1),
        span(text, "Restrepo", T.NOMBRE, "ia", nth=1),
    )
    assert len(review.entities) == 1
    assert apply_review(text, review)[0] == (
        "Visitamos a [NOMBRE_1]. [NOMBRE_1] comentó algo. [NOMBRE_1] firmó."
    )


def test_no_une_mencion_parcial_ambigua():
    text = "Juan Pérez y Juan Mora. Juan llegó."
    review = review_of(
        text,
        span(text, "Juan Pérez", T.NOMBRE),
        span(text, "Juan Mora", T.NOMBRE),
        span(text, "Juan", T.NOMBRE, nth=2),
    )
    assert len(review.entities) == 3


def test_une_variantes_de_empresa():
    text = "Soluciones Andinas S.A.S. contrata. Soluciones Andinas paga."
    review = review_of(
        text,
        span(text, "Soluciones Andinas S.A.S.", T.EMPRESA),
        span(text, "Soluciones Andinas", T.EMPRESA, nth=1),
    )
    assert len(review.entities) == 1


def test_valores_sin_digitos_en_tipo_numerico_no_se_unen():
    """Regresión: dos nombres marcados como CEDULA compartían la clave vacía."""
    text = "Juan Pérez y María López."
    review = review_of(
        text, span(text, "Juan Pérez", T.CEDULA), span(text, "María López", T.CEDULA)
    )
    assert len(review.entities) == 2


def test_desmarcar_no_reemplaza_y_renumera():
    text = "Ana Ruiz y Bogotá Pérez y Luis Mora."
    review = review_of(
        text,
        span(text, "Ana Ruiz", T.NOMBRE),
        span(text, "Bogotá Pérez", T.NOMBRE),
        span(text, "Luis Mora", T.NOMBRE),
    )
    review.set_enabled({review.entities[0].key, review.entities[2].key})
    out, summary = apply_review(text, review)
    assert out == "[NOMBRE_1] y Bogotá Pérez y [NOMBRE_2]."
    assert [s["label"] for s in summary] == ["[NOMBRE_1]", "[NOMBRE_2]"]
    assert all(set(s) == {"type", "description", "label", "count"} for s in summary)


def test_anadir_texto_que_se_escapo():
    text = "Vive en el barrio La Esperanza. La Esperanza es tranquila."
    review = ReviewData()
    entity = add_term(text, review, "La Esperanza", T.DIRECCION)
    assert entity.count == 2
    assert entity.sources == ["usuario"]
    out, _ = apply_review(text, review)
    assert out == "Vive en el barrio [DIRECCION_1]. [DIRECCION_1] es tranquila."


def test_anadir_respeta_espacios_y_mayusculas():
    text = "Firmó PEDRO   RAMÍREZ."
    review = ReviewData()
    add_term(text, review, "Pedro Ramírez", T.NOMBRE)
    assert apply_review(text, review)[0] == "Firmó [NOMBRE_1]."


def test_anadir_numero_con_otro_formato():
    text = "Cuenta 123-456-789 y también 123456789."
    review = ReviewData()
    add_term(text, review, "123456789", T.CUENTA)
    assert apply_review(text, review)[0] == "Cuenta [CUENTA_1] y también [CUENTA_1]."


def test_anadir_reemplaza_coincidencias_parciales():
    text = "Firma Juan Carlos Pérez Gómez."
    review = review_of(text, span(text, "Juan Carlos", T.NOMBRE, "ia"))
    add_term(text, review, "Juan Carlos Pérez Gómez", T.NOMBRE)
    assert len(review.entities) == 1
    assert apply_review(text, review)[0] == "Firma [NOMBRE_1]."


def test_anadir_valor_existente_lo_reactiva():
    text = "Ana Ruiz firmó."
    review = review_of(text, span(text, "Ana Ruiz", T.NOMBRE))
    review.set_enabled(set())
    add_term(text, review, "ana ruiz", T.NOMBRE)
    assert len(review.entities) == 1
    assert review.entities[0].enabled


@pytest.mark.parametrize(
    ("value", "message"),
    [("", "al menos 2"), ("x", "al menos 2"), ("No existe", "no aparece"), ("a" * 201, "largo")],
)
def test_anadir_errores(value, message):
    with pytest.raises(ReviewError, match=message):
        add_term("Texto del documento.", ReviewData(), value, T.NOMBRE)


def test_serializacion_ida_y_vuelta():
    text = "Ana Ruiz, C.C. 52.345.678"
    review = build_review(text, Anonymizer().find_spans(text))
    review.entities[0].enabled = False
    copy = ReviewData.from_dict(review.to_dict())
    assert copy.to_dict() == review.to_dict()
    assert apply_review(text, copy) == apply_review(text, review)
