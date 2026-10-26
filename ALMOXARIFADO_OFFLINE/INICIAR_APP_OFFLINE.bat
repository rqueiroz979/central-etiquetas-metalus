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
            echo Instale o Python 3.10+ e execute este arquivo novamente.
            pause
            exit /b 1
        )
    )
)

%PYTHON_CMD% -c "import sys; raise SystemExit(sys.version_info < (3, 10))"
if errorlevel 1 (
    echo Este app precisa do Python 3.10 ou superior.
    pause
    exit /b 1
)

%PYTHON_CMD% -c "import PySide6, reportlab" >nul 2>nul
if errorlevel 1 (
    echo Instalando dependencias do aplicativo...
    %PYTHON_CMD% -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Falha ao instalar as dependencias. Verifique a conexao e tente novamente.
        pause
        exit /b 1
    )
)

echo Iniciando ALMOXARIFADO...
%PYTHON_CMD% qt_app.py
pause
