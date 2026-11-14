# Dataset OCR local

Este directorio no debe contener documentos reales sin anonimización certificada.

El archivo `manifest.jsonl` usa una línea JSON por página:

```json
{"pdf":"scans/caso-001.pdf","page":1,"category":"scanned_bad","text":"texto ground truth","numerals":["1","1.1","2"],"expected_tables":0,"ground_truth_status":"verified"}
```

Distribución de liberación exigida: 10 PDF digitales, 10 escaneos buenos, 10 regulares y 10 malos. Ejecute:

```powershell
.venv-ocr\Scripts\python.exe benchmark_ocr.py tests\ocr_dataset\manifest.jsonl
```

Categorías válidas: `digital`, `scanned_good`, `scanned_regular` y
`scanned_bad`. Debe haber al menos 10 casos verificados de cada categoría.

Para crear un inventario inicial sin copiar los PDFs:

```powershell
.venv-ocr\Scripts\python.exe prepare_ocr_dataset.py "CARPETA_PDF"
```

El inventario no es ground truth: una persona debe anonimizar, revisar el texto,
etiquetar numerales/tablas y cambiar `ground_truth_status` a `verified`.

Para una comprobación reproducible sin documentos reales, el repositorio incluye
`generate_controlled_corpus.py`. Genera referencias sintéticas marcadas como
`ground_truth_origin=synthetic_generator`; sirven para probar rutas y métricas,
pero no cuentan como validación fiscal humana ni como evidencia del 99%.

Ejecute el benchmark definitivo con:

```powershell
.venv-ocr\Scripts\python.exe benchmark_ocr.py tests\ocr_dataset\local\manifest.jsonl
```

El release solo es promovible con detección de numerales >= 98.5%, fotocopias
malas >= 88%, tablas >= 95%, revisión humana <= 5% y las demás puertas del
reporte en estado verdadero.
