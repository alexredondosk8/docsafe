# DocSafe — Anonimizador local de documentos a Markdown

Aplicación web **local** (corre en tu PC, sin nube) que convierte documentos PDF, Word (.docx)
y Excel (.xlsx) a Markdown y elimina los datos personales y confidenciales, reemplazándolos
por etiquetas como `[NOMBRE_1]`, `[CEDULA_1]` o `[EMPRESA_1]`.

> Estado: **MVP en construcción** (Fase 4: anonimización por reglas; la detección con IA llega en la Fase 6).
> La guía completa de instalación en Windows y Linux, con Ollama, llega en la Fase 7.

## Requisitos
- Python 3.12
- [uv](https://docs.astral.sh/uv/) (gestor de dependencias)
- git (opcional, para el historial local)

## Instalación rápida (Windows PowerShell o Linux)
```bash
uv sync
```
Copia la plantilla de configuración y genera una clave secreta:
```bash
cp .env.example .env
uv run python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"
```
Pega la clave generada en `DJANGO_SECRET_KEY` dentro de `.env`. Luego inicia la aplicación
(aplica migraciones, arranca el procesador en segundo plano y el servidor web):
```bash
uv run python manage.py iniciar
```
Abre http://127.0.0.1:8000 en tu navegador. Para salir, Ctrl+C.

### Modo desarrollo (recarga automática al cambiar código)
En dos terminales:
```bash
uv run python manage.py runserver 127.0.0.1:8000
uv run python manage.py qcluster
```
Sin `qcluster` los documentos se quedan en «Pendiente».

## Modelo de lenguaje (Ollama)
Con [Ollama](https://ollama.com) instalado y en marcha, indica en `.env` el modelo a usar
(el nombre que muestra `ollama list`), por ejemplo `LLM_MODEL=qwen3:8b`, y reinicia la aplicación.
En **Configuración → Probar conexión** puedes comprobar que funciona.

## Pruebas y calidad
```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## Privacidad
- El servidor solo escucha en `127.0.0.1`: no es accesible desde otros equipos.
- Los archivos subidos y el texto original se borran al terminar el procesamiento.
- Si configuras un LLM remoto (una `LLM_BASE_URL` distinta de localhost), el contenido de
  tus documentos se enviará a ese servicio. La aplicación lo advertirá en la interfaz.

## Estructura
Ver [CLAUDE.md](CLAUDE.md) para la arquitectura, las decisiones y el plan por fases.
