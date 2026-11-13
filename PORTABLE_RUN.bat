@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title SSGT powered by FiscalOps
set "OLLAMA_NUM_PARALLEL=1"
set "OLLAMA_MAX_LOADED_MODELS=1"
set "OLLAMA_CONTEXT_LENGTH=2048"
set "OLLAMA_FLASH_ATTENTION=0"
set "RUNTIME=%~dp0runtime\python.exe"
if not exist "%RUNTIME%" set "RUNTIME=%~dp0runtime\Scripts\python.exe"
if not exist "%RUNTIME%" (
 echo [ERROR] Runtime no encontrado. Ejecute BUILD_PORTABLE.bat en el equipo de preparacion.
 exit /b 1
)
"%RUNTIME%" -B "%~dp0bootstrap.py" --check
if errorlevel 1 exit /b 1
if /i "%~1"=="--check" exit /b 0
"%RUNTIME%" -B "%~dp0launcher.py"
exit /b %errorlevel%
