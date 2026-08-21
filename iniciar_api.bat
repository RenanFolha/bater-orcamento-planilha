@echo off
setlocal

cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
) else (
    echo Ambiente virtual .venv nao encontrado. Usando o Python do sistema.
)

echo Iniciando API em http://localhost:8000
echo Documentacao: http://localhost:8000/docs
echo.

start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process 'http://localhost:8000/'"

python main.py

if errorlevel 1 (
    echo.
    echo Erro ao iniciar a API.
    pause
)
