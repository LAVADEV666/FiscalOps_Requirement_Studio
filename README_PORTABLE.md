# Ejecución portable

## Distribución lista para Windows

La distribución recomendada es `dist/FiscalOps-8.0.1-Windows-x64-Portable.zip`.
Extraiga **todo** el ZIP en una carpeta con permiso de escritura y abra
`FiscalOps.exe`. El EXE necesita las carpetas que lo acompañan. Se incluye el
runtime independiente, las dependencias y los cuatro modelos OCR de CPU para
Windows 10/11 x64; el arranque no instala paquetes ni descarga modelos.
Las bibliotecas nativas `msvcp140.dll` y `vcomp140.dll` se incluyen junto al
ejecutable de Python. La comprobación del portable confirma que se cargan
desde esa carpeta, en lugar de depender de las instaladas en el equipo.
WordCraft y todos los recursos de la interfaz también están incluidos.
La interfaz se abre en el navegador local. Mantenga abierta la consola mientras
trabaja y use el botón de cerrar de la aplicación o Ctrl+C para detenerla.

En esta distribución los datos se guardan en `datos_usuario` junto al EXE.
Para trasladarla con sus expedientes, cierre la aplicación y copie la carpeta
completa. Haga un respaldo de `datos_usuario` antes de borrar o actualizar el
programa. Para actualizar, extraiga el nuevo ZIP por separado y copie allí
`datos_usuario` con ambas versiones cerradas. `FISCALOPS_DATA_DIR` permite elegir
otra ubicación y tiene prioridad. Los lanzadores anteriores conservan sus rutas.
El marcador `portable.flag` activa esta ubicación en el EXE distribuido.

Para comprobar el paquete, ejecute `FiscalOps.exe --check` desde una terminal.
Para regenerarlo, use `BUILD_WINDOWS.bat` o
`runtime\python.exe -B build_windows.py`. Si ya existe una distribución, el
constructor se detiene para conservarla; use `--output otra_carpeta` para crear
otra. Compila el lanzador con .NET Framework de Windows, verifica las
dependencias desde la carpeta nueva y genera un manifiesto de archivos, un ZIP
con CRC comprobado y su SHA-256. No incluye expedientes, datos de empresas,
plantillas, ejemplos fiscales, entornos virtuales ni cachés OCR duplicadas.
Ollama, Donut y sus modelos opcionales se preparan por separado.

## Preparación del runtime

1. En el equipo de preparación, instale Python 3.13 x64 y ejecute
   `BUILD_PORTABLE.bat` con acceso a Internet. El preparador crea
   `runtime\python.exe` con la biblioteca estándar y las dependencias.
2. Copie el código, `static`, `paddle_ocr_engine`, los lanzadores y la carpeta
   `runtime` a la carpeta de destino. Ejecute `PORTABLE_RUN.bat --check`
   para verificar el entorno y `PORTABLE_RUN.bat` para iniciar. Este lanzador
   verifica dependencias con el runtime local y no instala paquetes.
3. Si ya existe un `runtime` creado como entorno virtual, muévalo antes de
   preparar el nuevo runtime. El lanzador reconoce la ruta heredada
   `runtime\Scripts\python.exe` para instalaciones que conservan su Python base.

La carpeta incluye Python 3.13.14 x64 en `runtime`. Tanto `run.bat` como `PORTABLE_RUN.bat` lo utilizan. También puedes preparar este runtime ejecutando `prepare_python313.py` desde otro Python instalado y después `run.bat` e `INSTALAR_OCR.bat`.

El paquete limpio excluye `work`, `data`, `corrections_store` y los ejemplos
fiscales. Los modelos de OCR se preparan aparte con `INSTALAR_OCR.bat`.

## Carpeta de expedientes

Una instalación nueva guarda expedientes en `%LOCALAPPDATA%\SSGT\FiscalOps`.
Para usar otra carpeta, defina `FISCALOPS_DATA_DIR` antes de iniciar cualquiera
de los lanzadores. Por ejemplo, en PowerShell:

```powershell
$env:FISCALOPS_DATA_DIR = 'D:\Expedientes\FiscalOps'
.\PORTABLE_RUN.bat
```

Una instalación existente sigue usando sus datos junto al programa. Para
migrarlos, cierre FiscalOps, copie `work`, `data` y `corrections_store` a la
nueva carpeta y arranque con la variable configurada. Compruebe la ruta en
**Diagnóstico y mantenimiento**. Desde ese panel también puede revisar la
retención y confirmar el borrado de las sesiones seleccionadas.

Para transferir un expediente individual, use **Respaldar expediente** y
**Restaurar respaldo**. El archivo ZIP contiene documentación fiscal y debe
guardarse en una ubicación autorizada.
