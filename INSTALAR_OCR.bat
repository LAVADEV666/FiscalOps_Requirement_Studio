@echo off
setlocal
cd /d "%~dp0"
set "FISCALOPS_PY=%~dp0runtime\python.exe"
if not exist "%FISCALOPS_PY%" set "FISCALOPS_PY=%~dp0.venv-ocr\Scripts\python.exe"
if not exist "%FISCALOPS_PY%" (
  echo [ERROR] Ejecute primero run.bat con Python 3.13 x64 instalado.
  pause
  exit /b 1
)
"%FISCALOPS_PY%" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :fatal
"%FISCALOPS_PY%" install_ocr.py
if errorlevel 1 goto :fatal
echo.
echo [OK] PaddleOCR y sus modelos locales quedaron preparados.
pause
exit /b 0
:fatal
echo.
echo [ERROR] No fue posible preparar PaddleOCR. Revise la salida anterior.
pause
exit /b 1
