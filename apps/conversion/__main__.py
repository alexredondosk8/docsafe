"""Convierte un documento a Markdown desde la terminal (herramienta de desarrollo).

ATENCIÓN: esta salida NO está anonimizada.

Uso:
    uv run python -m apps.conversion documento.pdf
    uv run python -m apps.conversion documento.docx -o salida.md
"""

import argparse
import sys
from pathlib import Path

from . import ConversionError, convert
from .base import ConversionResult


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m apps.conversion",
        description="Convierte un .pdf, .docx o .xlsx a Markdown (sin anonimizar).",
    )
    parser.add_argument("archivo", type=Path, help="documento a convertir")
    parser.add_argument("-o", "--salida", type=Path, help="archivo .md de salida")
    args = parser.parse_args(argv)

    file_type = args.archivo.suffix.lower().lstrip(".")
    if not args.archivo.is_file():
        print(f"No existe el archivo: {args.archivo}", file=sys.stderr)
        return 2
    try:
        result: ConversionResult = convert(args.archivo, file_type)
    except ConversionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    for warning in result.warnings:
        print(f"Aviso: {warning}", file=sys.stderr)
    if args.salida:
        args.salida.write_text(result.markdown, encoding="utf-8")
        print(f"Markdown guardado en {args.salida}", file=sys.stderr)
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(result.markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
