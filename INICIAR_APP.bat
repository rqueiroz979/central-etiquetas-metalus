@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
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

if not exist ".venv\Scripts\python.exe" (
    echo Criando ambiente virtual...
    %PYTHON_CMD% -m venv .venv
    if errorlevel 1 (
        echo Nao foi possivel criar o ambiente virtual.
        pause
        exit /b 1
    )
    set "PYTHON_CMD=.venv\Scripts\python.exe"
)

echo Instalando/atualizando dependencias...
%PYTHON_CMD% -m pip install --upgrade pip
if errorlevel 1 (
    echo Falha ao atualizar o pip.
    pause
    exit /b 1
)

%PYTHON_CMD% -m pip install -r requirements.txt
if errorlevel 1 (
    echo Falha ao instalar as dependencias.
    echo Verifique a conexao com a internet e tente novamente.
    pause
    exit /b 1
)

echo.
echo App iniciado.
echo Abra no navegador:
echo http://localhost:5000
echo.
echo Para acessar de outro PC na mesma rede:
echo 1. Descubra o IP deste computador com o comando ipconfig
echo 2. Abra http://IP_DESTE_COMPUTADOR:5000 no outro PC
echo.

%PYTHON_CMD% app.py
pause
