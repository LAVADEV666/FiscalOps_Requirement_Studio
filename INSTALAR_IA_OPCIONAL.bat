@echo off
setlocal
cd /d "%~dp0"
set "FISCALOPS_PY=%~dp0runtime\python.exe"
if not exist "%FISCALOPS_PY%" set "FISCALOPS_PY=%~dp0.venv-ocr\Scripts\python.exe"
if not exist "%FISCALOPS_PY%" (
  echo [ERROR] Ejecute primero run.bat para crear el entorno.
  pause
  exit /b 1
)
echo Instalando dependencias de IA. Este proceso puede tardar y requiere Internet.
"%FISCALOPS_PY%" -m pip install -r requirements-ai.txt
if errorlevel 1 (
  echo [ERROR] Revise la salida anterior.
  pause
  exit /b 1
)
echo.
echo Dependencias instaladas. Copie el modelo Donut en:
echo %CD%\models\donut-docvqa
pause
