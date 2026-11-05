# CLAUDE.md — DocSafe: anonimizador de documentos a Markdown (MVP)

Este archivo guía a Claude (y a cualquier persona) que trabaje en el proyecto.
Se mantiene actualizado al cerrar cada fase.

## Reglas de trabajo
- Rol: desarrollador senior Python/Django.
- Se trabaja POR FASES. Al terminar cada fase: detenerse, resumir lo hecho, explicar cómo
  probarlo y ESPERAR la aprobación del usuario antes de continuar.
- Ante una ambigüedad, preguntar en vez de suponer.
- Commit en git local al cerrar cada fase. Sin repositorio remoto ni CI/CD en el MVP.
- Antes de cerrar una fase: `uv run ruff check .`, `uv run ruff format --check .` y
  `uv run pytest` deben pasar.

## Objetivo
Aplicación web LOCAL (corre en el PC del usuario, un solo usuario, sin nube) que recibe un
documento (.pdf con texto, .docx, .xlsx), lo convierte a Markdown y lo ANONIMIZA: el .md
final no debe contener datos personales ni confidenciales.

Datos a reemplazar (mínimo): nombres de personas, documentos de identidad (cédula,
pasaporte…), edad, fecha de nacimiento, dirección, correo, teléfono, números de contrato,
nombre de empresa, NIT. Se reemplazan por etiquetas consistentes dentro del documento:
`[NOMBRE_1]`, `[CEDULA_1]`, `[EMPRESA_1]`, `[CORREO_1]`… (misma entidad → misma etiqueta).

## Stack
- Python 3.12 (fijado en `.python-version`), gestionado con **uv** (`pyproject.toml` + `uv.lock`).
- Django: la versión estable más reciente compatible con 3.12 (ver `uv.lock`).
- Plantillas Django + Bootstrap 5. JS mínimo (solo consulta periódica del estado).
- SQLite en `var/db.sqlite3`.
- Tareas en segundo plano: django-q2 con broker ORM (Fase 3).
- Configuración: `.env` + django-environ. Plantilla en `.env.example`.
- Calidad: ruff (lint + formato). Pruebas: pytest + pytest-django; el LLM siempre se simula en tests.

## Decisiones
1. **Idioma**: interfaz, mensajes, comentarios, docstrings y documentación en español.
   Identificadores de código (apps, modelos, funciones, variables) en inglés según la
   convención de Django. Etiquetas visibles (`verbose_name`, choices) en español.
2. **Núcleo independiente de Django**: `apps/conversion` y `apps/anonymization` contienen
   lógica en Python puro (sin importar Django en sus módulos de dominio) para probarla con
   pruebas unitarias rápidas.
3. **Datos de ejecución en `var/`** (base de datos, subidas temporales, logs); ignorado por git.
4. **Servidor solo en 127.0.0.1**: `ALLOWED_HOSTS` limitado a `127.0.0.1` y `localhost`.
5. **Privacidad**: nunca registrar datos personales en logs; el texto original, el archivo
   subido y el mapa etiqueta→valor real se borran al completar.
6. **LLM**: cliente único compatible con la API de OpenAI configurado solo por `.env`
   (`LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_TIMEOUT`). La clave nunca llega al navegador.
   El LLM devuelve JSON con entidades; el reemplazo lo hace el código.
7. Dependencias de cada fase se añaden en esa fase (no se instalan por adelantado).
8. **Django 6.1.3** (la más reciente compatible con 3.12 al iniciar). `requires-python = ">=3.12,<3.13"`.
9. **Sin admin ni autenticación** (`django.contrib.admin`/`auth` no instalados): uso personal
   en 127.0.0.1, menos superficie. Se usan sesiones solo para los mensajes de la UI.
10. **Bootstrap 5.3.8 local** en `static/vendor/` (sin CDN): funciona sin internet y no hace
    peticiones externas. Una prueba verifica que las páginas no cargan recursos remotos.
11. **whitenoise** sirve CSS/JS también con `DEBUG=False` (`WHITENOISE_USE_FINDERS=True`,
    sin necesidad de `collectstatic`).
12. **Pruebas aisladas del `.env` del usuario**: `config/settings_test.py` apunta
    `DOCSAFE_ENV_FILE` a un archivo inexistente y usa una carpeta `var` temporal.
13. `DJANGO_SECRET_KEY` es obligatoria: sin ella la aplicación no arranca.

## Arquitectura (carpetas)
```
config/              Proyecto Django (settings, settings_test, urls, wsgi, asgi)
apps/documents/      Modelo de conversión, subida, historial, vista previa, descarga, revisión
apps/conversion/     PDF/DOCX/XLSX → Markdown (determinista)
apps/anonymization/  Regex, detector LLM, fragmentación, mapa de entidades, reemplazo
apps/llm/            Cliente compatible con OpenAI, página de Configuración, prueba de conexión
templates/           Plantillas globales (base.html)
static/              CSS/JS propios
var/                 db.sqlite3, uploads/, logs/ (no versionado)
tests/               unit/, integration/, e2e/, fixtures/
```

## Comandos
```
uv sync                                   # instalar dependencias
uv run python manage.py migrate           # crear/actualizar base de datos
uv run python manage.py runserver 127.0.0.1:8000
uv run pytest                             # pruebas
uv run ruff check . ; uv run ruff format .
```

## Fases
0. Estructura, entorno, settings, .env.example, ruff, pytest, CLAUDE.md, README. ✅
1. Subida y validación (1 archivo, ≤ 20 MB, extensión + MIME) + modelo + historial.
2. Conversión determinista a Markdown (PDF, DOCX, XLSX) con archivos de ejemplo.
3. Segundo plano (django-q2), estados y progreso en la UI.
4. Anonimización determinista (regex) con pruebas.
5. Cliente LLM, página de Configuración, probar conexión, aviso de privacidad.
6. Anonimización con LLM, fragmentación, etiquetas consistentes, pantalla de revisión.
7. Endurecimiento, pruebas de extremo a extremo, README completo (Windows/Linux + Ollama).

## Preguntas abiertas
- Pantalla de revisión (Fase 6): ¿solo confirmar/cancelar o también desmarcar/añadir
  reemplazos? ¿Se muestra el valor original de forma temporal hasta confirmar?
- Conversión PDF (Fase 2): `pymupdf4llm` es AGPL; aceptable para uso personal, revisar
  si se distribuye. Evaluar frente a `markitdown`.
