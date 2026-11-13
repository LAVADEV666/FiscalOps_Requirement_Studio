@echo off
setlocal
cd /d "%~dp0"
echo FiscalOps v8.0.1 Stable - Preparador portable
where py >nul 2>nul || (echo [ERROR] Python no localizado.& pause & exit /b 1)
set "PYTHON_CMD="
py -3.13 -c "import sys" >nul 2>nul && set "PYTHON_CMD=py -3.13"
if not defined PYTHON_CMD py -3.12 -c "import sys" >nul 2>nul && set "PYTHON_CMD=py -3.12"
if not defined PYTHON_CMD py -3.11 -c "import sys" >nul 2>nul && set "PYTHON_CMD=py -3.11"
if not defined PYTHON_CMD py -3.10 -c "import sys" >nul 2>nul && set "PYTHON_CMD=py -3.10"
if not defined PYTHON_CMD (echo [ERROR] Se requiere Python 3.10 a 3.13 x64.& pause & exit /b 1)
%PYTHON_CMD% build_portable.py
if errorlevel 1 (echo [ERROR] No fue posible preparar el runtime.& pause & exit /b 1)
echo [OK] Runtime portable preparado. Use PORTABLE_RUN.bat.
pause
