# Arquitectura OCR FiscalOps

## Contrato

La UI y el workspace existente se conservan. `ocr_engine.OCREngine` es un adaptador estable hacia `paddle_ocr_engine/`, el único motor OCR. Todas las confianzas usan escala `0..1` y cada bloque conserva `bbox`, `motor`, texto y estado de revisión.

Python 3.12 y 3.13 usan PaddlePaddle 3.2.2 y PaddleOCR 3.3.2 mediante `modern.py`. El reconocimiento utiliza PP-OCRv5 móvil con modelo latino y orientación de líneas. PP-DocLayout-S identifica tablas y figuras para exportar sus recortes originales. Estos modelos se guardan en `models/paddleocr/v3`. Python 3.10 y 3.11 mantienen el adaptador de PaddleOCR 2.9.1 y sus modelos anteriores.

## Pipeline

1. PyMuPDF clasifica cada página y el extractor aprovecha el texto nativo legible.
2. Las páginas escaneadas se renderizan hasta 300 DPI. PaddleOCR prueba primero la imagen original y, según la calidad, compara variantes de contraste y enderezado.
3. El motor procesa en CPU con lotes de una imagen. La selección considera confianza, cobertura y numerales detectados. Las coordenadas se proyectan de vuelta sobre la página original.
4. El analizador local identifica tablas y figuras con PP-DocLayout-S o PP-Structure según la versión de Python.
5. **OCR por zonas** permite revisar recortes de varias páginas, forzar lectura por imagen y confirmar correcciones antes de actualizar un numeral. Estas correcciones se guardan en el expediente. Las revisiones de bloques históricos siguen registradas en `corrections_store/`.

Las tablas regulares se exportan como celdas editables. Para estructuras irregulares se conserva un recorte. La auditoría de Word comprueba los elementos visuales vinculados por identificador.

## Privacidad

No existe fallback remoto ni Tesseract. Los modelos residen en `models/paddleocr/`; su descarga ocurre mediante `INSTALAR_OCR.bat`. El runtime no necesita red después de la instalación.

## Corrección local controlada

`paddle_ocr_engine.corrector.OllamaCorrector` usa exclusivamente el endpoint
loopback de Ollama y el modelo `gemma3:4b`. Opera con contexto 2048,
temperatura cero y `keep_alive=0`. El resultado es una sugerencia, nunca una
mutación automática. Antes de mostrarla se comprueba que conserve numerales,
cifras, fechas y RFC, además de una similitud mínima con el OCR original.

## Puerta de validación

`prepare_ocr_dataset.py` inventaría casos sin copiar documentos.
`benchmark_ocr.py` rechaza etiquetas no verificadas, enruta páginas digitales
por PyMuPDF y escaneadas por PaddleOCR, y evalúa las puertas constitucionales
por categoría. Los reportes no incluyen texto reconocido ni imágenes.

La validación amplia de escaneos sigue pendiente. El protocolo usa 10 PDF digitales y 30 escaneados anonimizados, divididos en grupos de calidad buena, regular y mala. Los objetivos incluyen detección de numerales de al menos 98.5%, exactitud de caracteres de al menos 88% en escaneos malos, detección de tablas de al menos 95%, revisión humana de hasta 5% y hasta 60 segundos por página. Consulta [el formato del dataset](../tests/ocr_dataset/README.md).

## Integración mínima autorizada

`processing_pipeline.py` pasa el adaptador al extractor heredado y `audit_engine.py` utiliza coordenadas OCR reales para páginas escaneadas. El editor, Word, evidencia y cumplimiento no se reemplazan.
