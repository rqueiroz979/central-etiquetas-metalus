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

if not exist "build\package-data" mkdir "build\package-data"
%BUILD_PYTHON% -c "from pathlib import Path; import shutil; files=list(Path('.').glob('*.ods')); assert len(files) == 1, files; shutil.copy2(files[0], Path('build/package-data/template.ods'))"
if errorlevel 1 exit /b 1

%BUILD_PYTHON% -m PyInstaller --clean --noconfirm --onefile --name CentralEtiquetasMetalus --distpath dist\windows --workpath build\windows-work --specpath build\windows-spec --collect-all reportlab --collect-all ezodf --collect-all lxml --add-data "%CD%\templates;templates" --add-data "%CD%\static;static" --add-data "%CD%\config.json;." --add-data "%CD%\build\package-data\template.ods;." app.py
if errorlevel 1 exit /b 1

echo Executable created at dist\windows\CentralEtiquetasMetalus.exe