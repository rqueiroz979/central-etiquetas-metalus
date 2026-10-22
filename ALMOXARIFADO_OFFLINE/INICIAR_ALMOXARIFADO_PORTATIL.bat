@echo off
setlocal
cd /d "%~dp0"

if not exist "ALMOXARIFADO.exe" (
    echo ALMOXARIFADO.exe nao foi encontrado nesta pasta.
    pause
    exit /b 1
)

start "" "%~dp0ALMOXARIFADO.exe"
