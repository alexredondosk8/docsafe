# DocSafe — Anonimizador local de documentos a Markdown

DocSafe convierte documentos **PDF** (con texto), **Word (.docx)** y **Excel (.xlsx)** a
Markdown y **elimina los datos personales y confidenciales**: los reemplaza por etiquetas
consistentes como `[NOMBRE_1]`, `[CEDULA_1]`, `[EMPRESA_1]` o `[CORREO_1]` (la misma persona
o empresa recibe siempre la misma etiqueta dentro del documento).

Todo ocurre **en tu PC**: es una aplicación web que solo escucha en `127.0.0.1`, sin cuentas,
sin nube y sin enviar nada a internet (salvo que configures a propósito un modelo de IA remoto).

## Cómo funciona
1. **Subes** un documento (uno a la vez, hasta 20 MB).
2. Se **convierte** a Markdown (títulos, listas y tablas incluidos).
3. Se **detectan** los datos sensibles en dos capas:
   - **Reglas**: cédulas, NIT, correos, teléfonos, direcciones, fechas de nacimiento, edades,
     números de contrato y de cuenta, empresas con sufijo societario, nombres con contexto
     («Sr.», «representada por»…) y columnas de tablas con cabeceras conocidas.
   - **IA local** (opcional, con [Ollama](https://ollama.com)): nombres, empresas y direcciones
     escritos de forma libre que las reglas no reconocen.
4. **Revisas** la lista de reemplazos: desmarcas lo que no sea un dato personal y añades lo que
   se haya escapado. La vista previa muestra el resultado.
5. **Confirmas** y **descargas** el `.md` anonimizado. En ese momento se borran el texto original
   y los valores reales; si no confirmas, se borran solos a las 24 horas.

Datos que se reemplazan: nombres de personas, cédula y otros documentos de identidad, pasaporte,
NIT, nombre de empresa, correo, teléfono, dirección, fecha de nacimiento, edad, número de
contrato y cuentas bancarias.

## Requisitos
- Windows 10/11 o Linux (probado en Windows 11 y Ubuntu en WSL).
- [uv](https://docs.astral.sh/uv/) (gestor de Python). **No necesitas instalar Python**: uv
  descarga Python 3.12 automáticamente.
- Opcional, para la detección con IA: [Ollama](https://ollama.com) y unos 8 GB de RAM libres
  (ver [Modelo de lenguaje](#modelo-de-lenguaje-ollama)).
- Alrededor de 1 GB de disco para Python y las dependencias (más el modelo de IA si lo usas).

## Instalación

### 1. Instalar uv
**Windows** (PowerShell):
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```
**Linux**:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```
Cierra y vuelve a abrir la terminal para que el comando `uv` esté disponible.

### 2. Obtener el proyecto e instalar las dependencias
Copia la carpeta del proyecto a tu equipo (por ejemplo `C:\Proyecto\docsafe` o `~/docsafe`),
entra en ella y ejecuta:
```bash
uv sync
```

### 3. Configurar
Copia la plantilla de configuración (el mismo comando sirve en PowerShell y en Linux):
```bash
cp .env.example .env
```
Genera una clave secreta:
```bash
uv run python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"
```
Abre `.env` con un editor de texto y pega la clave en `DJANGO_SECRET_KEY=`. Sin ella la
aplicación no arranca.

### 4. Iniciar
```bash
uv run python manage.py iniciar
```
Abre **http://127.0.0.1:8000** en tu navegador. Para salir, pulsa **Ctrl+C** en la terminal.

`iniciar` prepara la base de datos, arranca el procesador en segundo plano y el servidor web.
Si el puerto 8000 está ocupado: `uv run python manage.py iniciar --puerto 8001`.

## Modelo de lenguaje (Ollama)
Sin IA, DocSafe funciona solo con reglas y avisa de que la anonimización es parcial. Con IA
detecta además nombres, empresas y direcciones mencionados de forma libre.

1. **Instala Ollama**
   - Windows: descarga el instalador desde [ollama.com/download](https://ollama.com/download).
     Queda funcionando en segundo plano (icono junto al reloj).
   - Linux: `curl -fsSL https://ollama.com/install.sh | sh`
2. **Descarga un modelo**:
   ```bash
   ollama pull qwen3:8b
   ```
   `qwen3:8b` es el modelo con el que se probó DocSafe (descarga de unos 5 GB; conviene tener
   8 GB de RAM libres). Con menos memoria usa `qwen3:4b`, que es más rápido pero detecta menos.
3. **Configura `.env`**:
   ```ini
   LLM_BASE_URL=http://localhost:11434/v1
   LLM_MODEL=qwen3:8b
   ```
4. Reinicia DocSafe y entra en **Configuración → Probar conexión**.

Tiempos orientativos con `qwen3:8b` en un PC sin GPU dedicada: 25-35 s para un contrato de dos
páginas. Los documentos grandes se dividen en fragmentos y la página muestra el avance.

## Configuración (`.env`)
| Variable | Por defecto | Qué hace |
|---|---|---|
| `DJANGO_SECRET_KEY` | — | Clave secreta. **Obligatoria.** |
| `DJANGO_DEBUG` | `False` | Solo `True` mientras desarrollas. |
| `DOCSAFE_MAX_UPLOAD_MB` | `20` | Tamaño máximo por archivo. |
| `DOCSAFE_TIME_ZONE` | `America/Bogota` | Zona horaria de las fechas que muestra la aplicación. |
| `DOCSAFE_LOG_LEVEL` | `INFO` | Detalle de los logs en `var/logs/` (nunca incluyen datos personales). |
| `DOCSAFE_VAR_DIR` | `./var` | Carpeta de la base de datos, archivos temporales y logs. |
| `DOCSAFE_ANONIMIZAR_TODAS_LAS_FECHAS` | `False` | `True` reemplaza todas las fechas, no solo las de nacimiento. |
| `DOCSAFE_REGLAS_DESACTIVADAS` | vacío | Tipos que no se anonimizan, p. ej. `EDAD,CUENTA`. |
| `DOCSAFE_USAR_IA` | `True` | `False` usa solo reglas: no se envía nada al modelo. |
| `DOCSAFE_IA_TAMANO_FRAGMENTO` | `2500` | Caracteres por fragmento enviado al modelo. |
| `DOCSAFE_REVISION_HORAS` | `24` | Horas que se guardan los originales esperando tu revisión. |
| `DOCSAFE_TASK_TIMEOUT` | `14400` | Segundos máximos de procesamiento por documento. |
| `LLM_BASE_URL` | `http://localhost:11434/v1` | Servidor del modelo (API compatible con OpenAI). |
| `LLM_MODEL` | vacío | Nombre del modelo (`ollama list`). Vacío = sin IA. |
| `LLM_API_KEY` | vacío | Clave del proveedor (Ollama no la necesita). |
| `LLM_TIMEOUT` | `120` | Segundos máximos por petición al modelo. |
| `LLM_REASONING_EFFORT` | `none` | `none` desactiva el razonamiento previo de qwen3 (unas 6 veces más rápido). |

Tras cambiar `.env`, reinicia DocSafe (Ctrl+C y `iniciar` de nuevo).

## Privacidad
- El servidor solo escucha en `127.0.0.1`: otros equipos de la red no pueden acceder.
- El archivo subido se borra al terminar el procesamiento. El texto original y los valores
  reales solo se guardan mientras la conversión está **«En revisión»**: se borran al confirmar,
  al descartar o a las 24 horas.
- Se conservan el Markdown anonimizado, el nombre original del archivo (para reconocerlo en el
  historial) y la lista de reemplazos **sin los valores reales**. Puedes eliminar cada entrada
  desde el historial.
- Los logs nunca contienen texto de los documentos ni datos personales.
- Si configuras un modelo **remoto** (una `LLM_BASE_URL` que no sea `localhost`/`127.0.0.1`,
  incluida una IP de tu red local), el contenido de tus documentos se envía a ese servicio. La
  aplicación lo advierte en la subida y en Configuración.
- La página no carga nada de internet (Bootstrap va incluido) y aplica una política de
  seguridad de contenido estricta.

**Revisa siempre el resultado antes de compartirlo.** Ninguna detección automática es perfecta.

## Limitaciones
- PDF escaneados (imágenes sin texto) no se procesan: no hay reconocimiento óptico (OCR).
- PDF y documentos de Office protegidos con contraseña se rechazan, igual que `.doc`/`.xls`
  antiguos: guárdalos como `.docx`/`.xlsx`.
- En Word no se incluyen imágenes, cuadros de texto, notas al pie, comentarios ni control de
  cambios. En Excel se usan los valores de fórmula que Excel guardó.
- Las ciudades no se anonimizan.

## Solución de problemas
| Problema | Solución |
|---|---|
| El documento se queda en «Pendiente» | El procesador no está en marcha. Usa `iniciar` (o, en modo desarrollo, `qcluster` en otra terminal). |
| «El puerto 8000 ya está en uso» | Cierra el otro servidor (Ctrl+C en su ventana) o usa `--puerto 8001`. |
| «Ya hay un procesador de DocSafe en marcha» | Ciérralo con Ctrl+C en su ventana. Si quedó sin ventana, el mensaje indica el comando para cerrarlo (`taskkill /PID … /T /F` en Windows, `kill …` en Linux). |
| Ctrl+C no detiene el servidor (Windows) | Pulsa **Ctrl+Pausa**. |
| La terminal deja de avanzar (Windows) | Si hiciste clic dentro de la ventana, Windows pausa el programa en «modo de selección»: pulsa Esc o Enter. |
| «No se pudo conectar… ¿Está Ollama en marcha?» | Abre Ollama (Windows) o ejecuta `ollama serve` (Linux). Comprueba con `ollama list` que el modelo existe. |
| «Tiempo de espera agotado» con la IA | El modelo tarda en cargar la primera vez. Sube `LLM_TIMEOUT` (p. ej. `300`) o usa un modelo más pequeño. |
| La primera conversión de PDF tarda más | Normal: se carga el analizador de diseño (~1 s). |
| «Revisión caducada» | Pasaron más de `DOCSAFE_REVISION_HORAS` sin confirmar; los originales se borraron. Sube el documento de nuevo. |

## Modo desarrollo
Con recarga automática al cambiar el código, en dos terminales:
```bash
uv run python manage.py runserver 127.0.0.1:8000
```
```bash
uv run python manage.py qcluster
```
Convertir un archivo a Markdown desde la terminal, **sin anonimizar** (útil para depurar):
```bash
uv run python -m apps.conversion documento.pdf -o salida.md
```

## Pruebas y calidad
```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```
Las pruebas de extremo a extremo usan un navegador real (Chromium, con Playwright). Instálalo
una vez; si falta, esas pruebas se omiten:
```bash
uv run playwright install chromium
```
En Linux, además, instala las librerías del sistema que necesita Chromium (pide la contraseña
de administrador): `uv run playwright install --with-deps chromium`.

Solo las de extremo a extremo: `uv run pytest -m e2e`. Todas menos esas: `uv run pytest -m "not e2e"`.
Las pruebas nunca usan tu `.env` ni un modelo de IA real.

## Licencias
La conversión de PDF usa PyMuPDF / pymupdf4llm, con licencia **AGPL-3.0**: válida para uso
personal; si algún día se distribuye DocSafe, hay que revisar esta condición.

## Más información
[CLAUDE.md](CLAUDE.md) describe la arquitectura, las decisiones técnicas y el plan por fases.
