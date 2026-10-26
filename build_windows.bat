@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python 3.10+ is required on the build computer.
    exit /b 1
)

python -c "import sys; raise SystemExit(sys.version_info < (3, 10))"
if errorlevel 1 (
    echo Python 3.10 or newer is required on the build computer.
    exit /b 1
)

if not exist ".build-windows\Scripts\python.exe" (
    python -m venv .build-windows
    if errorlevel 1 exit /b 1
)

set "BUILD_PYTHON=.build-windows\Scripts\python.exe"
%BUILD_PYTHON% -m pip install --upgrade pip
if errorlevel 1 exit /b 1
%BUILD_PYTHON% -m pip install -r requirements-build.txt
if errorlevel 1 exit /b 1

%BUILD_PYTHON% -m PyInstaller --clean --noconfirm --onedir --windowed --name ALMOXARIFADO --distpath dist\windows --workpath build\windows-work --specpath build\windows-spec --paths "%CD%\ALMOXARIFADO_OFFLINE" --collect-all reportlab --hidden-import PySide6.QtPdf --hidden-import PySide6.QtPdfWidgets --hidden-import PySide6.QtPrintSupport --add-data "%CD%\ALMOXARIFADO_OFFLINE\static;static" --add-data "%CD%\ALMOXARIFADO_OFFLINE\config.json;." "%CD%\ALMOXARIFADO_OFFLINE\qt_app.py"
if errorlevel 1 exit /b 1

copy /Y "ALMOXARIFADO_OFFLINE\INICIAR_ALMOXARIFADO_PORTATIL.bat" "dist\windows\ALMOXARIFADO\INICIAR_ALMOXARIFADO.bat" >nul
if errorlevel 1 exit /b 1

type nul > "dist\windows\ALMOXARIFADO\portable.flag"

echo Windows package created at dist\windows\ALMOXARIFADO