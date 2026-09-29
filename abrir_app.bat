@echo off
setlocal
cd /d "%~dp0"

echo Iniciando Equalizador de Propostas...
where py >nul 2>&1
if not errorlevel 1 (
    py -3 iniciar_app.py
) else (
    python iniciar_app.py
)

if errorlevel 1 (
    echo.
    echo Nao foi possivel iniciar o aplicativo.
    echo O inicializador tentou criar o ambiente e instalar as dependencias.
    pause
)
