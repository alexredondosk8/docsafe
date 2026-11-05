"""Reglas de expresiones regulares para datos personales y confidenciales (Colombia).

Cada regla indica el tipo de entidad, el patrón y qué grupo del patrón es el dato.
Las palabras clave ("C.C.", "NIT", "nacido el"...) dan contexto y evitan confundir, por
ejemplo, una cédula con un valor en pesos. Las abreviaturas cortas (C.C., CC, T.I.) se
comparan respetando mayúsculas; las palabras completas, sin distinguirlas.
"""

import re
from dataclasses import dataclass

from .entities import EntityType

# --- Piezas reutilizables ---------------------------------------------------------------

_NUM_LABEL = r"(?:(?i:no|n[°º]|nro|n[uú]m(?:ero)?)\.?\s*)?"  # "No.", "N°", "número"…
_SEP = r"[\s:|.]*"  # separadores entre palabra clave y valor (incluye celdas de tabla)

_MONTHS = (
    r"(?i:enero|febrero|marzo|abril|mayo|junio|julio|agosto|sept?iembre|octubre|"
    r"noviembre|diciembre)"
)
DATE = (
    r"(?:\d{1,2}[/.-]\d{1,2}[/.-](?:\d{4}|\d{2})"
    r"|\d{4}-\d{1,2}-\d{1,2}"
    rf"|\d{{1,2}}\s+(?i:de)\s+{_MONTHS}\s+(?i:del?)\s+\d{{4}})"
)

_UPPER = "A-ZÁÉÍÓÚÑÜ"
_LOWER = "a-záéíóúñü"
# Nombre de persona: 2 a 5 palabras con mayúscula inicial (admite "de", "del", "de la").
NAME = (
    rf"[{_UPPER}][{_LOWER}]+"
    rf"(?:\s+(?:(?:de|del)\s+(?:(?:la|las|los)\s+)?)?[{_UPPER}][{_LOWER}]+){{1,4}}"
)

_ID_NUMBER = r"(\d{1,3}(?:[.\s]\d{3}){1,3}|\d{5,12})(?![\d])"
_CODE = r"((?=[A-Za-z0-9/._-]*\d)[A-Za-z0-9](?:[A-Za-z0-9/._-]*[A-Za-z0-9])?)"

_COMPANY_WORD = r"[A-ZÁÉÍÓÚÑ0-9][\w&'.-]*"
_COMPANY_CONNECTOR = r"(?:de|del|la|las|los|y|e|&)"
_COMPANY_SUFFIX = (
    r"(?:S\.?\s?A\.?\s?S\.?|S\.?\s?en\s?C\.?(?:\s?S\.?)?|S\.?\s?C\.?\s?A\.?|S\.\s?A\.?|SA"
    r"|Ltda\.?|LTDA\.?|E\.?\s?U\.?|E\.?\s?S\.?\s?P\.?)"
)

_VIA = (
    r"(?i:(?:avenida|av\.?)\s+(?:calle|carrera|cra|kr|cl)|calle|cll|cl|carrera|cra|kra|kr|cr"
    r"|avenida|av|ak|ac"
    r"|diagonal|dg|transversal|tv|tr|circular|autopista)\.?"
)
_ADDRESS_COMPLEMENT = (
    r"(?:\s*,?\s*(?i:apto|apartamento|oficina|of|interior|int|piso|torre|casa|local|bloque|bl)"
    r"\.?\s*[\w-]+)*"
)
ADDRESS = (
    rf"\b{_VIA}\s*\d{{1,3}}\s?[A-Za-z]?(?:\s?(?i:bis))?(?:\s?[A-Za-z])?"
    r"(?:\s+(?i:sur|este|norte|oeste))?"
    r"\s*(?:#|(?i:no|n[°º]|nro|n[uú]mero)\.?)\s*"
    r"\d{1,3}\s?[A-Za-z]?(?:\s?(?i:bis))?\s*-\s*\d{1,3}(?:\s+(?i:sur|este))?"
    rf"{_ADDRESS_COMPLEMENT}"
)


@dataclass(frozen=True)
class Rule:
    name: str
    type: EntityType
    pattern: re.Pattern
    group: int = 1
    priority: int = 0
    # Palabras iniciales a recortar (p. ej. "Entre Soluciones Andinas S.A.S.").
    trim_leading_stopwords: bool = False


def single_line(pattern: str) -> str:
    r"""Hace que ``\s`` no cruce saltos de línea: lo cambia por espacio o tabulador.

    Evita que una coincidencia una dos párrafos (p. ej. un título con el párrafo siguiente).
    """
    out, i, in_class = [], 0, False
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\" and i + 1 < len(pattern):
            pair = pattern[i : i + 2]
            if pair == r"\s":
                out.append(r" \t" if in_class else r"[ \t]")
            else:
                out.append(pair)
            i += 2
            continue
        if ch == "[" and not in_class:
            in_class = True
            out.append(ch)
            # Un "]" justo al inicio (o tras "^") es literal.
            if pattern[i + 1 : i + 2] == "^":
                out.append("^")
                i += 1
            if pattern[i + 1 : i + 2] == "]":
                out.append("]")
                i += 1
        elif ch == "]" and in_class:
            in_class = False
            out.append(ch)
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _rule(name, entity_type, pattern, group=1, priority=0, trim=False) -> Rule:
    return Rule(name, entity_type, re.compile(single_line(pattern)), group, priority, trim)


PRIORITY = {
    EntityType.CORREO: 90,
    EntityType.NIT: 80,
    EntityType.CEDULA: 70,
    EntityType.PASAPORTE: 70,
    EntityType.CUENTA: 65,
    EntityType.TELEFONO: 60,
    EntityType.CONTRATO: 55,
    EntityType.FECHA_NACIMIENTO: 50,
    EntityType.EDAD: 50,
    EntityType.DIRECCION: 45,
    EntityType.EMPRESA: 40,
    EntityType.NOMBRE: 30,
    EntityType.FECHA: 10,
}


def build_rules(anonymize_all_dates: bool = False) -> list[Rule]:
    T = EntityType
    p = PRIORITY
    rules = [
        # --- Correo -----------------------------------------------------------------------
        _rule(
            "correo",
            T.CORREO,
            r"(?<![\w.+-])([A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})(?!\w)",
            priority=p[T.CORREO],
        ),
        # --- NIT --------------------------------------------------------------------------
        _rule(
            "nit_con_palabra_clave",
            T.NIT,
            rf"(?i:\bNIT\b)\.?{_SEP}{_NUM_LABEL}[:.]?\s*"
            r"(\d{3}\.?\d{3}\.?\d{3}(?:\s?-\s?\d)?|\d{8,10}(?:\s?-\s?\d)?)(?!\d)",
            priority=p[T.NIT],
        ),
        _rule(
            "nit_formato",
            T.NIT,
            r"(?<![\d.])(\d{3}\.\d{3}\.\d{3}\s?-\s?\d)(?!\d)",
            priority=p[T.NIT],
        ),
        # --- Documentos de identidad ------------------------------------------------------
        _rule(
            "cedula_con_palabra_clave",
            T.CEDULA,
            r"(?:(?<![\w.])(?:C\.\s?C\.?|CC|C\.\s?E\.?|CE|T\.\s?I\.?|TI|NUIP)(?!\w)"
            r"|(?i:\bc[ée]dula(?:\s+de\s+(?:ciudadan[ií]a|extranjer[ií]a))?"
            r"|\btarjeta\s+de\s+identidad|\bdocumento(?:\s+de\s+identidad)?"
            r"|\bn[uú]mero\s+de\s+identificaci[oó]n|\bidentificaci[oó]n))"
            rf"{_SEP}{_NUM_LABEL}[:.]?\s*{_ID_NUMBER}",
            priority=p[T.CEDULA],
        ),
        _rule(
            "pasaporte",
            T.PASAPORTE,
            rf"(?i:\bpasaporte){_SEP}{_NUM_LABEL}[:.]?\s*([A-Z]{{0,3}}\d{{5,10}}[A-Z]?)(?![\w])",
            priority=p[T.PASAPORTE],
        ),
        # --- Cuenta bancaria --------------------------------------------------------------
        _rule(
            "cuenta_bancaria",
            T.CUENTA,
            r"(?i:cuenta\s+(?:de\s+)?(?:ahorros|corriente)|cta\.?\s*(?:de\s+)?(?:ahorros|cte\.?|corriente))"
            r"[^\n\d|]{0,25}(\d[\d\s.-]{4,22}\d)(?!\d)",
            priority=p[T.CUENTA],
        ),
        # --- Teléfono ---------------------------------------------------------------------
        _rule(
            "celular_colombia",
            T.TELEFONO,
            r"(?<![\d+])((?:\+\s?57[\s.-]?|57[\s.-])?3\d{2}[\s.-]?\d{3}[\s.-]?\d{4})(?!\d)",
            priority=p[T.TELEFONO],
        ),
        _rule(
            "fijo_colombia",
            T.TELEFONO,
            r"(?<![\d+])((?:\+\s?57[\s.-]?|57[\s.-])?\(?60[1-8]\)?[\s.-]?\d{3}[\s.-]?\d{4})(?!\d)",
            priority=p[T.TELEFONO],
        ),
        _rule(
            "telefono_internacional",
            T.TELEFONO,
            r"(?<![\w+])(\+\d{1,3}[\s.-]?\(?\d{1,4}\)?(?:[\s.-]?\d{2,4}){2,4})(?!\d)",
            priority=p[T.TELEFONO],
        ),
        _rule(
            "telefono_con_palabra_clave",
            T.TELEFONO,
            r"(?i:\btel[eé]fonos?|\btel|\bcel(?:ular)?|\bm[óo]vil|\bwhatsapp|\bpbx|\bfax)\.?"
            rf"{_SEP}{_NUM_LABEL}[:.]?\s*(\(?\+?\d[\d\s().-]{{5,18}}\d)(?!\d)",
            priority=p[T.TELEFONO],
        ),
        # --- Contrato ---------------------------------------------------------------------
        _rule(
            "contrato_numero",
            T.CONTRATO,
            r"(?i:\bcontrato\b)[^\n|]{0,80}?"
            r"(?:(?i:\bno\b|\bnro\b|\bn[uú]mero\b)\.?|(?i:\bn)[°º]\.?|#)\s*[:.]?\s*" + _CODE,
            priority=p[T.CONTRATO],
        ),
        _rule(
            "numero_de_contrato",
            T.CONTRATO,
            r"(?i:n[uú]mero\s+del?\s+contrato|no\.?\s+(?:del?\s+)?contrato|contrato\s+n[uú]mero)"
            rf"{_SEP}{_CODE}",
            priority=p[T.CONTRATO],
        ),
        # --- Fecha de nacimiento y edad ---------------------------------------------------
        _rule(
            "fecha_nacimiento",
            T.FECHA_NACIMIENTO,
            r"(?i:nacid[oa]s?|naci[oó]|nacimiento|f\.\s?nac\.?|fecha\s+nac\.?)"
            rf"[^\n\d|]{{0,30}}(?<!\d)({DATE})(?!\d)",
            priority=p[T.FECHA_NACIMIENTO],
        ),
        _rule(
            "edad_palabra_clave",
            T.EDAD,
            r"(?i:\bedad)\s*(?:(?i:de)\s*)?[:|]?\s*(?<!\d)(\d{1,3}(?:\s*(?i:a[ñn]os))?)(?!\d)",
            priority=p[T.EDAD],
        ),
        _rule(
            "edad_anos_de_edad",
            T.EDAD,
            r"(?<!\d)(\d{1,3}\s*(?i:a[ñn]os))\s+(?i:de\s+edad|cumplidos)",
            priority=p[T.EDAD],
        ),
        _rule(
            "edad_tras_nacimiento",
            T.EDAD,
            r"(?i:nacid[oa]|naci[oó])[^\n|]{0,60}?\(?(?<!\d)(\d{1,3}\s*(?i:a[ñn]os))(?!\w)",
            priority=p[T.EDAD],
        ),
        # --- Dirección --------------------------------------------------------------------
        _rule("direccion", T.DIRECCION, f"({ADDRESS})", priority=p[T.DIRECCION]),
        # --- Empresa (por sufijo societario) ----------------------------------------------
        _rule(
            "empresa_sufijo",
            T.EMPRESA,
            rf"(?<![\w.])((?:{_COMPANY_WORD}\s+(?:{_COMPANY_CONNECTOR}\s+)?){{1,6}}?"
            rf"{_COMPANY_SUFFIX})(?![\w])",
            priority=p[T.EMPRESA],
            trim=True,
        ),
        # --- Nombres de persona (solo con contexto claro; el LLM completa en Fase 6) -----
        _rule(
            "nombre_tratamiento",
            T.NOMBRE,
            r"(?:\b(?:Sr|Sra|Srta|Dr|Dra|Ing|Lic)\.|(?i:\bseñor(?:a|ita)?|\bdoctor(?:a)?|\bdon|\bdoña))"
            rf"\s+({NAME})",
            priority=p[T.NOMBRE],
        ),
        _rule(
            "nombre_representante",
            T.NOMBRE,
            r"(?i:representad[oa]s?(?:\s+legalmente)?\s+por|en\s+representaci[oó]n\s+de)"
            rf"\s+(?:(?i:el\s+señor|la\s+señora)\s+)?({NAME})",
            priority=p[T.NOMBRE],
        ),
        _rule(
            "nombre_antes_de_identificacion",
            T.NOMBRE,
            rf"({NAME}),?\s+(?=(?i:identificad[oa]s?\s+con\s+(?:la\s+)?"
            r"(?:c[ée]dula|c\.?\s?c|pasaporte|c\.?\s?e|t\.?\s?i|documento|tarjeta)"
            r"|mayor(?:es)?\s+de\s+edad|portador(?:a)?\s+de))",
            priority=p[T.NOMBRE],
            trim=True,
        ),
        _rule(
            "empresa_antes_de_nit",
            T.EMPRESA,
            rf"((?:{_COMPANY_WORD}\s+(?:{_COMPANY_CONNECTOR}\s+)?){{0,5}}{_COMPANY_WORD}),?\s+"
            r"(?=(?i:identificad[oa]\s+con\s+(?:el\s+)?NIT|con\s+NIT|NIT\b))",
            priority=p[T.EMPRESA] - 1,
            trim=True,
        ),
        _rule(
            "nombre_campo",
            T.NOMBRE,
            r"(?i:\bnombre(?:s)?(?:\s+completo|\s+y\s+apellidos)?|\bcontratista|\btrabajador"
            r"|\bempleado|\bfirma|\bfirmado\s+por|\batentamente)"
            rf"\s*[:,]\s*({NAME})",
            priority=p[T.NOMBRE],
        ),
    ]
    if anonymize_all_dates:
        rules.append(
            _rule("fecha", T.FECHA, rf"(?<![\d/.-])({DATE})(?![\d/])", priority=p[T.FECHA])
        )
    return rules


# Palabras que no forman parte de un nombre de persona o empresa al inicio de la coincidencia.
LEADING_STOPWORDS = {
    "entre", "y", "e", "el", "la", "los", "las", "señor", "señora", "sr", "sra", "don",
    "doña", "con", "por", "de", "del", "a", "al", "que", "firma", "contratista",
    "contratante", "empresa", "sociedad", "en", "según", "para", "sin", "ante", "señores",
    "cliente", "proveedor", "nit", "razón", "social",
}  # fmt: skip
