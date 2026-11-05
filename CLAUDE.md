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
14. **Nombre original del archivo**: se guarda en el historial (decisión del usuario, Fase 1)
    para reconocer cada documento. Nunca se escribe en logs ni se usa como ruta en disco
    (el archivo se guarda como `<uuid>.<ext>`). El usuario puede eliminar cada entrada
    (registro + archivo) desde el historial o el detalle.
15. **Validación del tipo real sin python-magic** (`apps/documents/validation.py`, Python puro):
    PDF por cabecera `%PDF-`; DOCX/XLSX por ZIP + `[Content_Types].xml` con el tipo principal
    correcto (rechaza .docm/.xlsm renombrados). Detecta OLE (.doc/.xls o Office con contraseña)
    con mensaje específico. Protección contra bombas ZIP (máx. 10 000 entradas, 500 MB sin comprimir).
16. **Modelo `Conversion`** (`apps/documents/models.py`): id UUID, estados en inglés con etiquetas
    en español (pending, converting, anonymizing, review, completed, error), `progress` 0-100,
    `markdown` (solo el resultado anonimizado), `upload` temporal en `var/uploads`.
    `UploadsStorage` lee `settings.UPLOADS_DIR` en cada uso (las pruebas lo aíslan por test).
17. **Un archivo por subida** validado en navegador (`static/js/upload.js`) y en servidor.
    El tamaño se valida tras recibir el archivo; cortar la subida antes queda para la Fase 7.
18. Rutas: `/` subir, `/historial/`, `/conversiones/<uuid>/`, `/conversiones/<uuid>/eliminar/` (POST).

### Conversión a Markdown (Fase 2) — evaluación y elección
Se comparó markitdown 0.1.9 con pymupdf4llm 2.1 / python-docx / openpyxl sobre los mismos
documentos de ejemplo (`tests/fixtures/`, datos ficticios):

| Formato | Elegido | Por qué no markitdown |
|---|---|---|
| PDF | **pymupdf4llm** (modo diseño, `use_ocr=False`) | markitdown (pdfminer) da texto plano sin títulos ni tablas, corta líneas a mitad de frase y deja ligaduras ("ﬁ") que rompen las regex. pymupdf4llm reconoce títulos, listas y tablas con bordes y une las líneas en párrafos (un nombre no queda partido). |
| DOCX | **conversor propio con python-docx** | mammoth (dentro de markitdown) omite encabezados/pies, crea una fila vacía como cabecera de tabla y no escapa `\|` (rompe tablas). |
| XLSX | **conversor propio con openpyxl** | usa pandas: `NaN`, `NaT`, `5000000.0`, no escapa `\|`. |

Además markitdown arrastra `magika` (modelo de IA para detectar tipos) y pandas.

Detalles:
- `apps/conversion/` es Python puro. Entrada: `convert(path, file_type) -> ConversionResult(markdown, warnings)`;
  errores como `ConversionError` con mensaje en español sin contenido del documento.
- `normalize()` aplica NFKC (ligaduras, espacios duros), saltos `\n`, máx. una línea en blanco,
  línea en blanco tras títulos. Común a los tres formatos para que la anonimización sea uniforme.
- **PDF**: rechaza protegidos con contraseña y escaneados (ninguna página con ≥ 10 caracteres de texto);
  en PDF mixtos omite páginas sin texto y avisa. Quita la negrita redundante en títulos.
  Licencia **AGPL** (PyMuPDF): válida para uso personal; revisar si algún día se distribuye.
  Trae onnxruntime y modelos de diseño **locales** (~90 MB, sin descargas en ejecución).
  La primera conversión de PDF tarda ~1 s más (carga del modelo).
- **DOCX**: orden original; títulos (Heading/Título N, Title, outlineLvl), negrita/cursiva, listas con
  viñeta/numeradas y anidadas (numbering.xml), tablas (primera fila = cabecera, celdas combinadas
  sin duplicar, tablas anidadas aplanadas), enlaces (mailto/tel como texto), controles de contenido.
  Encabezados arriba y pies abajo, separados con `---` (sin duplicados). No incluye: imágenes,
  cuadros de texto, notas al pie, comentarios, control de cambios.
- **XLSX**: `## Hoja: <nombre>` por hoja (ocultas incluidas y marcadas), primera fila = cabecera,
  sin filas/columnas vacías, fechas ISO, enteros sin `.0`, porcentajes según formato, booleanos Sí/No.
  Usa los valores de fórmula guardados por Excel; si el archivo no los tiene (p. ej. generado por
  código), la celda queda vacía.
- Herramienta de terminal (sin anonimizar): `uv run python -m apps.conversion archivo [-o salida.md]`.
- Documentos de ejemplo: `uv run python -m tests.fixtures.generate` (regenera `tests/fixtures/`).

### Procesamiento en segundo plano (Fase 3)
- **django-q2 1.11** con broker ORM, 1 worker, `max_attempts=1`, `save_limit=-1` (no guarda resultados
  exitosos). Probado en Windows. En pruebas `Q_CLUSTER["sync"]=True` (se ejecuta en el mismo proceso).
- **SQLite en modo WAL** + `transaction_mode=IMMEDIATE` + `timeout=20`: web y worker escriben a la vez.
- Flujo (`apps/documents/pipeline.py`): pendiente → convirtiendo (10 %) → anonimizando (50-95 %)
  → completado (100 %) / error. La tarea solo recibe el id y no devuelve nada; **todas** las excepciones
  se capturan dentro (django-q nunca guarda trazas que podrían contener texto). Errores inesperados:
  mensaje genérico al usuario y en logs solo el tipo de excepción.
- Cambios de estado con `UPDATE` por id: si se elimina la conversión durante el proceso, la tarea
  se detiene (`Cancelled`) sin recrear el registro.
- El archivo subido se borra siempre al terminar (éxito o error).
- Reintento: una conversión no terminada (p. ej. el worker se cayó) se reprocesa desde el inicio.
  `iniciar` vuelve a encolar las conversiones sin terminar al arrancar (encolar dos veces es inocuo).
- `ANONYMIZATION_ENABLED = False` en `pipeline.py` hasta la Fase 4: la UI advierte que el Markdown
  contiene datos originales. `pipeline.anonymize()` es el punto de enganche de las Fases 4-6.
- UI: `/conversiones/<uuid>/estado/` (JSON sin contenido, `no-store`), consultado cada 1,5 s por
  `static/js/status.js`; recarga al terminar; pista tras 15 s en «Pendiente». Vista previa en `<pre>`
  (texto escapado) y descarga `/conversiones/<uuid>/descargar/` (`<nombre>.md`, solo si completado).
- Campo `Conversion.warnings` (JSON, lista de avisos sin contenido).
- `manage.py iniciar [--puerto]`: migra, reencola, lanza `qcluster` como subproceso y `runserver`
  en 127.0.0.1 sin recarga; al salir detiene el worker. Desarrollo: runserver + qcluster en 2 terminales.
- `iniciar` se niega a arrancar si ya hay un `qcluster` de este proyecto en marcha (psutil): dos
  procesadores comparten la cola ORM y uno con código antiguo procesaría documentos con reglas
  viejas (ocurrió en la verificación de la Fase 4).

### Anonimización por reglas (Fase 4)
Paquete `apps/anonymization/` (Python puro):
- `entities.py`: `EntityType` (NOMBRE, CEDULA, PASAPORTE, NIT, EMPRESA, CORREO, TELEFONO, DIRECCION,
  FECHA_NACIMIENTO, EDAD, CONTRATO, CUENTA, FECHA), `Span`, `EntityMap` (etiquetas `[TIPO_n]`
  numeradas por tipo en orden de aparición; misma entidad ⇒ misma etiqueta según `normalize_value`:
  dígitos para documentos/teléfonos, NIT sin DV, correo en minúsculas, texto sin tildes ni mayúsculas,
  empresa sin puntos/espacios). `clear()` borra los valores reales.
- `rules.py`: reglas regex con contexto colombiano (C.C./CC/C.E./T.I./NUIP, NIT con o sin DV, celulares 3xx,
  fijos 60x, internacionales +, palabra clave "Tel/Cel", cuentas de ahorros/corrientes, "nacido el" + fecha,
  edad con "edad"/"años de edad"/tras nacimiento, nomenclatura de direcciones (Calle, Cra., Av. Calle,
  Diagonal… # n-n + complementos), empresas por sufijo societario (S.A.S., S.A., Ltda., E.U., S. en C.…)
  o seguidas de "identificada con NIT", nombres solo con contexto (Sr./Dra./señora, "representada por",
  "…, identificado con C.C.", "Firma:/Nombre:"). Abreviaturas cortas sensibles a mayúsculas.
  `single_line()` convierte `\s` en `[ \t]` al compilar: **ninguna coincidencia cruza saltos de línea**.
- `tables.py`: tablas Markdown. Columna con cabecera conocida (Nombre, Cédula, Correo, Teléfono, Dirección,
  Fecha de nacimiento, Edad, NIT, Contrato, Empresa/Razón social, Cuenta, Pasaporte) ⇒ todas sus celdas.
  Tabla clave-valor (2 columnas, alguna fila del cuerpo empieza con etiqueta conocida) ⇒ segunda celda.
  Respeta `\|` escapado; ignora celdas vacías, "-", "N/A".
- `anonymizer.py`: detectores → filtro de tipos desactivados → **propagación** (cada valor detectado se busca
  en todo el texto; numéricos con separadores flexibles; EDAD y FECHA no se propagan; mín. 4 caracteres /
  5 dígitos) → solapamientos (mayor prioridad, luego más largo) → reemplazo. `Anonymizer` acepta
  `extra_detectors` (LLM en Fase 6) y un `EntityMap` compartido entre fragmentos.
- Configuración `.env`: `DOCSAFE_ANONIMIZAR_TODAS_LAS_FECHAS` (False por defecto, decisión del usuario:
  solo fechas de nacimiento) y `DOCSAFE_REGLAS_DESACTIVADAS` (lista de tipos; tipo desconocido ⇒ error al arrancar).
- Integración (`pipeline.anonymize`): guarda el Markdown anonimizado y `Conversion.replacements`
  (tipo, descripción, etiqueta, apariciones — **sin valores reales**); el mapa se borra al terminar.
  La UI muestra la tabla "Reemplazos realizados" y un aviso de anonimización parcial mientras
  `ANONYMIZATION_LAYERS` no incluya "llm".
- Limitaciones conocidas (para el LLM en Fase 6): nombres/empresas/direcciones en texto libre sin
  contexto; variantes de un mismo nombre ("Juan Pérez" vs "Juan Carlos Pérez Gómez") reciben etiquetas
  distintas; ciudades no se anonimizan; una celda de la columna "Nombre" que no es un nombre se
  reemplaza igual (se prefiere anonimizar de más).

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
uv run python manage.py iniciar           # uso normal: migra + worker + servidor (127.0.0.1:8000)
uv run python manage.py runserver 127.0.0.1:8000   # desarrollo, junto con:
uv run python manage.py qcluster                   # procesador en segundo plano
uv run pytest                             # pruebas
uv run ruff check . ; uv run ruff format .
```

## Fases
0. Estructura, entorno, settings, .env.example, ruff, pytest, CLAUDE.md, README. ✅
1. Subida y validación (1 archivo, ≤ 20 MB, extensión + MIME) + modelo + historial. ✅
2. Conversión determinista a Markdown (PDF, DOCX, XLSX) con archivos de ejemplo. ✅
3. Segundo plano (django-q2), estados y progreso en la UI. ✅
4. Anonimización determinista (regex) con pruebas. ✅
5. Cliente LLM, página de Configuración, probar conexión, aviso de privacidad.
6. Anonimización con LLM, fragmentación, etiquetas consistentes, pantalla de revisión.
7. Endurecimiento, pruebas de extremo a extremo, README completo (Windows/Linux + Ollama).

## Preguntas abiertas
- Pantalla de revisión (Fase 6): ¿solo confirmar/cancelar o también desmarcar/añadir
  reemplazos? ¿Se muestra el valor original de forma temporal hasta confirmar?
- (Resuelta en Fase 2) PDF con pymupdf4llm (AGPL, aceptable para uso personal).
