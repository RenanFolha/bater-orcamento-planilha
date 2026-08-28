@echo off
setlocal

cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
) else (
    echo Ambiente virtual .venv nao encontrado. Usando o Python do sistema.
)

if exist "certs\chave.pem" if exist "certs\certificado.pem" (
    rem Certificado encontrado -- sobe acessivel pela rede local via HTTPS
    rem (ver main.py: HOST diferente de localhost exige certificado TLS).
    set HOST=0.0.0.0
    set SSL_KEYFILE=certs\chave.pem
    set SSL_CERTFILE=certs\certificado.pem
    echo Iniciando API em https://localhost:8000 ^(tambem acessivel na rede local^)
    echo Documentacao: https://localhost:8000/docs
    echo.
    echo O navegador pode avisar que a conexao "nao e segura" -- e esperado com
    echo certificado autoassinado. Clique em Avancado / Continuar mesmo assim.
    echo.
    start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process 'https://localhost:8000/'"
) else (
    echo Iniciando API em http://localhost:8000 ^(sem certificado em certs\ -- so acessivel nesta maquina^)
    echo Documentacao: http://localhost:8000/docs
    echo.
    start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process 'http://localhost:8000/'"
)

python main.py

if errorlevel 1 (
    echo.
    echo Erro ao iniciar a API.
    pause
)
