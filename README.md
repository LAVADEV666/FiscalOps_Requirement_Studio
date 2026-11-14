# SSGT powered by FiscalOps

FiscalOps es una aplicación local de escritorio para revisar requerimientos en PDF, editar numerales y respuestas, y exportar a Word con plantillas por RFC.

## Puesta en marcha

Para compartir una versión lista para usar en Windows 10/11 x64, genere el
paquete con `BUILD_WINDOWS.bat`. El ZIP de `dist` incluye `FiscalOps.exe`, Python
y los modelos OCR. Extraiga todo y abra el EXE; los expedientes se guardarán en
`datos_usuario` junto al programa. Consulte [la guía portable](README_PORTABLE.md).

1. Abre `run.bat`. Da prioridad al Python de `runtime` y después al entorno `.venv-ocr`. Esta carpeta incluye un runtime independiente de Python 3.13.14 x64.
2. Para una instalación nueva con Python 3.13 x64 instalado, `run.bat` crea `.venv-ocr` e instala sus dependencias. Ejecuta `INSTALAR_OCR.bat` una vez con conexión para preparar los modelos.
3. La aplicación se ejecuta en `http://127.0.0.1:6969`. Usa `run.bat --check` para comprobar la instalación.

`prepare_python313.py` prepara el runtime oficial de Python 3.13.14 desde otro Python instalado. Verifica el SHA-256 de la descarga y requiere conexión. Después ejecuta `run.bat` e `INSTALAR_OCR.bat`. Python 3.10 y 3.11 siguen usando la versión anterior del motor. Python 3.12 y 3.13 utilizan PaddleOCR 3.

Para releer parte de un documento, activa **OCR por zonas** en el visor del PDF. Marca el recorte, revisa el resultado y aplícalo al numeral. En **Plantillas Word** puedes guardar un DOCX para el primer requerimiento y otro para el segundo por RFC.

### WordCraft y diseño de plantillas

La interfaz principal ocupa el viewport y se organiza en **Importar PDF**, **Expedientes**, **Resguardos**, **Plantillas** y **Ajustes**. Las listas usan paginación ajustada al espacio disponible; los documentos y contenidos extensos se desplazan dentro de su panel. En ventanas estrechas puedes alternar **Expediente / PDF original** y desplegar **Resumen** para consultar los indicadores. La búsqueda, el orden, los filtros, la densidad y la última pestaña se conservan en el navegador.

En **Expedientes**, las acciones **···** permiten asignar grupo, marcar favoritos, archivar y crear un resguardo local. Las tarjetas de **Empresas → Personalizar** admiten un PNG de hasta 4 MB, un emoji corporativo y un color de fondo. Puedes desactivar la portada para volver al icono sin borrar el PNG.

**Resguardos** conserva copias ZIP independientes en `data/resguardos`, con comprobación SHA-256 antes de descargar o restaurar. Restaurar crea una sesión nueva y conserva el expediente original. **Importar ZIP** sigue admitiendo los respaldos descargados anteriormente. En el menú del expediente también están disponibles **Guardar resguardo local** y **Descargar respaldo ZIP**.

La depuración nunca es automática. En **Expedientes → Sesiones**, el **tache (×)** retira una sesión directamente a `work/.trash`, sin límite de antigüedad ni validador escrito. **Deshacer** la recupera inmediatamente; también permanece disponible en **Ajustes → Registros retirados**. Para depurar varias, usa **Mostrar sesiones**, **Seleccionar todas** o marca registros concretos y pulsa **Retirar seleccionadas**. Una antigüedad de **0** incluye todas. La eliminación definitiva sigue siendo una segunda acción por registro, con botones Cancelar/Eliminar y sin escribir palabras de confirmación. Los resguardos independientes se conservan.

Los acentos visuales combinan púrpura SSGT y cian discreto, con la firma **Powered by FiscalOps**. El símbolo PNG proporcionado se conserva sin modificar en `static/ssgt-symbol.png`: se encuadra al renderizar, se usa como estela de mouse y acelera/desacelera como motor durante las cargas y el procesamiento. En **Ajustes → Presentación** puedes desactivar las animaciones o la estela. Se respeta la preferencia de movimiento reducido; la estela no se activa con gestos táctiles ni al arrastrar texto.

La portada, el color y el emoji registrados por RFC se reutilizan en el encabezado del expediente, Estudio Word, WordCraft, la biblioteca de plantillas, su diseñador y su vista previa. Los cambios de apariencia se propagan a las vistas abiertas del mismo RFC. Esta identificación visual no modifica automáticamente el contenido del DOCX.


**Estudio Word → WordCraft profesional** abre el editor web oficial WordCraft 0.14.0 dentro de FiscalOps, sin conexión. Permite trabajar con sus herramientas de formato, tablas, imágenes, revisión, referencias e importación/exportación disponibles en la versión web. Elige continuar el escrito guardado o generar uno nuevo desde Estudio Word, con formato estándar o con una plantilla por RFC.

Usa **Ctrl+S** o **Archivo → Guardar** en WordCraft para guardar el DOCX en el expediente; **Descargar DOCX** obtiene la versión guardada. Las exportaciones PDF y otros formatos se descargan. El escrito profesional se conserva en `work/<sesión>/wordcraft/document.docx` y viaja con el respaldo del expediente. Sus ediciones no se trasladan automáticamente a los numerales del modelo OCR; al generar un escrito nuevo se vuelve a partir de Estudio Word. Si otro editor guardó primero, se bloquea la sobrescritura y se ofrece una copia de recuperación.

WordCraft ocupa toda la ventana. **← Volver al editor** mantiene el documento abierto, incluyendo cambios pendientes, selección e historial de deshacer. **Retomar WordCraft** regresa a ese mismo editor. Si falla el guardado, los bytes pendientes se conservan para reintentar o descargar una copia de recuperación. Guarda antes de cerrar o recargar el navegador. En teléfonos se compacta la cinta nativa; las opciones de zoom, vista y estadísticas siguen disponibles en **Vista** y **Revisar**.

En **Plantillas Word**, busca un RFC o selecciónalo en la biblioteca. Asigna un icono y color, elige el primer o segundo requerimiento y usa **En blanco**, **Carta base** o importa un DOCX. **Abrir WordCraft** permite editar el diseño completo; **Vista previa** muestra las páginas guardadas. **Editar bloques y OCR → Colocar rectángulo OCR** cambia el punto de inserción. El borde opcional identifica esa zona en el DOCX base: al exportar se sustituye por el contenido y crece según los numerales, tablas e imágenes. Conserva `{{REQUERIMIENTO}}` una sola vez, como párrafo independiente en el cuerpo del documento, al editar en WordCraft.

WordCraft necesita WebGL2 o WebGPU en el navegador. La distribución web, sus fuentes, avisos y licencias MIT/Apache se incluyen en `static/vendor/wordcraft`. La vista previa usa docx-preview 0.3.7 y JSZip 3.10.1 locales y es orientativa; revisa el resultado en WordCraft antes de exportar. Procedencia y hashes: `static/vendor/wordcraft/fiscalops-vendor.json` y `static/vendor/docx-preview/sources.json`. El protocolo oficial usado está documentado en [WordCraft host.rs](https://github.com/storytold/wordcraft/blob/v0.14.0/apps/wordcraft-web/src/host.rs).

Consulta [la guía portable](README_PORTABLE.md) para preparar otra computadora y [la arquitectura OCR](docs/OCR_ARCHITECTURE.md) para el funcionamiento y la validación del motor.

### Inteligencia documental híbrida local

El pipeline inspecciona el 100% de las páginas, clasifica cada una, conserva
la extracción nativa y utiliza el PaddleOCR incluido solo en páginas escaneadas
o regiones visuales mixtas. La reconstrucción, validación cruzada y
interpretación quedan guardadas en el expediente con trazabilidad por página.

Ollama es opcional y permanece desactivado por defecto. Puede activarse y
seleccionarse el modelo desde **Ajustes → Inteligencia documental local**. Para
establecer la configuración inicial de una sesión local también puede usar:

```powershell
$env:FISCALOPS_OLLAMA_ENABLED="1"
$env:FISCALOPS_OLLAMA_MODEL="qwen2.5:3b"
$env:FISCALOPS_OLLAMA_URL="http://localhost:11434"
```

Modelos soportados inicialmente: `qwen2.5:3b`, `qwen2.5:1.5b` y
`llama3.2:3b`. Comprueba instalación, latencia y disponibilidad en **Ajustes**
o mediante `/api/ollama/status`. La configuración de la interfaz se aplica a
la sesión actual mediante `/api/ollama/config`. Si Ollama está apagado o el
modelo no está instalado, el flujo determinista y PaddleOCR continúan funcionando.

En documentos escaneados, `FISCALOPS_OCR_DET_LIMIT_SIDE_LEN` controla el lado
máximo de detección PaddleOCR (por defecto `2048`, acotado entre `1024` y
`4096`). La imagen original nunca se modifica.

## Datos locales

Una instalación nueva guarda sus datos en `%LOCALAPPDATA%\SSGT\FiscalOps`. Las instalaciones anteriores pueden seguir usando `work`, `data` y `corrections_store` junto al programa. La variable `FISCALOPS_DATA_DIR` tiene prioridad sobre esas rutas. Consulta **Diagnóstico y mantenimiento** para confirmar la ubicación activa.

Conserva `work` para los expedientes y sus revisiones, `data` para empresas y plantillas, y `corrections_store` para las correcciones históricas de OCR. Usa **Respaldar expediente** para transferir un expediente. Los ejemplos fiscales, los modelos descargados y los datos de operación se excluyen del control de versiones.

## Verificación y mantenimiento

Usa el mismo intérprete para ejecutar la aplicación y las pruebas. Con el runtime incluido, los comandos son los siguientes.

```powershell
.\runtime\python.exe -m pip install -r requirements-dev.txt
.\runtime\python.exe -B -m pytest -p no:cacheprovider -q
```

`startup.log` corresponde al último arranque. `app.log` se guarda en la carpeta de datos y rota al alcanzar 1 MiB. Los PDFs temporales de las cargas completadas se retiran tras guardar el expediente con su PDF original.

La integración opcional de Donut se instala con `INSTALAR_IA_OPCIONAL.bat` en el intérprete seleccionado. Requiere un modelo local en `models/donut-docvqa` y se comprueba con `/api/ai/status`.
