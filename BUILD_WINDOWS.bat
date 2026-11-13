@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not exist "runtime\python.exe" (
  echo [ERROR] Prepare primero el runtime y los modelos OCR.
  pause
  exit /b 1
)
"runtime\python.exe" -B build_windows.py %*
if errorlevel 1 (
  echo [ERROR] No se pudo crear la distribucion.
  pause
  exit /b 1
)
echo [OK] Distribucion disponible en dist.
pause
