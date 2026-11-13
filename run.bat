@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title FiscalOps Requirement Studio v8.0.1 Stable - NO CERRAR
color 0F
set "OLLAMA_NUM_PARALLEL=1"
set "OLLAMA_MAX_LOADED_MODELS=1"
set "OLLAMA_CONTEXT_LENGTH=2048"
set "OLLAMA_FLASH_ATTENTION=0"

set "VENV_PY=%CD%\runtime\python.exe"
if exist "%VENV_PY%" goto :runtime_ready
set "VENV_PY=%CD%\.venv-ocr\Scripts\python.exe"
if exist "%VENV_PY%" goto :runtime_ready

set "PYTHON_CMD="
py -3.13 -c "import sys" >nul 2>nul && set "PYTHON_CMD=py -3.13"
if not defined PYTHON_CMD py -3.12 -c "import sys" >nul 2>nul && set "PYTHON_CMD=py -3.12"
if not defined PYTHON_CMD py -3.11 -c "import sys" >nul 2>nul && set "PYTHON_CMD=py -3.11"
if not defined PYTHON_CMD py -3.10 -c "import sys" >nul 2>nul && set "PYTHON_CMD=py -3.10"
if not defined PYTHON_CMD (
  echo [ERROR] Instale Python 3.13 x64 o prepare el runtime con prepare_python313.py.
  goto :fatal
)
echo [1/3] Creando entorno virtual local...
%PYTHON_CMD% -m venv ".venv-ocr"
if errorlevel 1 goto :fatal
set "VENV_PY=%CD%\.venv-ocr\Scripts\python.exe"

:runtime_ready
if /i "%~1"=="--check" (
  "%VENV_PY%" -B bootstrap.py --check
  if errorlevel 1 exit /b 1
  exit /b 0
)

echo [2/3] Verificando dependencias...
"%VENV_PY%" -B bootstrap.py > startup.log 2>&1
if errorlevel 1 (
  echo [ERROR] No fue posible instalar o verificar las dependencias.
  echo Revise startup.log en esta carpeta.
  goto :fatal
)

echo [3/3] Iniciando servidor en http://127.0.0.1:6969
echo.
"%VENV_PY%" -B launcher.py
set "EXIT_CODE=%ERRORLEVEL%"

if "%EXIT_CODE%"=="0" goto :normal

echo.
echo [ERROR] El servidor termino con codigo %EXIT_CODE%.
echo Revise startup.log y la ruta de app.log indicada por el servidor.
goto :fatal

:normal
echo.
echo La aplicacion se detuvo correctamente.
pause
exit /b 0

:fatal
echo.
echo La ventana permanecera abierta para que pueda revisar el error.
pause
exit /b 1
