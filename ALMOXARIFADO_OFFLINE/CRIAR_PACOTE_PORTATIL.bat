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
            pause
            exit /b 1
        )
    )
)

echo Verificando PyInstaller...
%PYTHON_CMD% -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
    echo PyInstaller nao esta instalado neste ambiente.
    echo Instale com: %PYTHON_CMD% -m pip install pyinstaller
    pause
    exit /b 1
)

echo Criando pacote portatil...
%PYTHON_CMD% -m PyInstaller --clean --noconfirm almoxarifado_offline.spec
if errorlevel 1 (
    echo Falha ao criar o pacote portatil.
    pause
    exit /b 1
)

if not exist "dist\ALMOXARIFADO" (
    echo Pasta dist\ALMOXARIFADO nao foi gerada.
    pause
    exit /b 1
)

copy /Y "config.json" "dist\ALMOXARIFADO\config.json" >nul
xcopy /E /I /Y "data" "dist\ALMOXARIFADO\data" >nul
xcopy /E /I /Y "static" "dist\ALMOXARIFADO\static" >nul
copy /Y "INICIAR_ALMOXARIFADO_PORTATIL.bat" "dist\ALMOXARIFADO\INICIAR_ALMOXARIFADO.bat" >nul

echo.
echo Pacote pronto em:
echo %CD%\dist\ALMOXARIFADO
echo.
echo Copie a pasta ALMOXARIFADO inteira para o outro PC.
pause
