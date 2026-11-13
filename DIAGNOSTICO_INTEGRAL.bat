@echo off
setlocal
cd /d "%~dp0"
echo === SSGT powered by FiscalOps ===
set "DIAG_PY=%~dp0runtime\python.exe"
if not exist "%DIAG_PY%" set "DIAG_PY=%~dp0runtime\Scripts\python.exe"
if not exist "%DIAG_PY%" set "DIAG_PY=%~dp0.venv-ocr\Scripts\python.exe"
if not exist "%DIAG_PY%" (
 echo [ERROR] No se encontro el runtime local. Prepare el entorno antes del diagnostico.
 exit /b 1
)
"%DIAG_PY%" -B -c "import sys; from config import DATA_ROOT; print('Python:', sys.version.split()[0]); print('Carpeta de datos:', DATA_ROOT)"
"%DIAG_PY%" -B "%~dp0bootstrap.py" --check
if errorlevel 1 exit /b 1
echo Consulte Diagnostico y mantenimiento dentro de FiscalOps para revisar OCR, almacenamiento y retencion.
pause
