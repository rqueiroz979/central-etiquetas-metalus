@echo off
setlocal
cd /d "%~dp0"

if exist "..\.venv\Scripts\python.exe" (
    set "PYTHON_CMD=..\.venv\Scripts\python.exe"
) else if exist ".venv\Scripts\python.exe" (
    set "PYTHON_CMD=.venv\Scripts\python.exe"
) else (
    where py >nul 2>nul
    if %errorlevel%==0 (
        set "PYTHON_CMD=py -3"
    ) else (
        where python >nul 2>nul
        if %errorlevel%==0 (
            set "PYTHON_CMD=python"
        ) else (
            echo Python nao foi encontrado neste computador.
            echo Instale o Python 3.11+ e execute este arquivo novamente.
            pause
            exit /b 1
        )
    )
)

echo Iniciando ALMOXARIFADO...
%PYTHON_CMD% qt_app.py
pause
