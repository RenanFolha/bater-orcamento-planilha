# Desenvolvedor Chefe: RenanFolha

"""
API de Orçamento de Frete

Lê as regras de precificação do banco SQLite (frete.db) e expõe
endpoints para calcular o frete, resolver endereços/filiais e recarregar
os parâmetros depois de editar o banco.

Rodar localmente:
    python main.py
    (ou) uvicorn main:app --reload --port 8000

Documentação interativa (Swagger):
    http://localhost:8000/docs

As rotas em si vivem em routers/ (auth, geo, orcamento, historico,
parametros, admin_precos, admin_usuarios) — este arquivo só monta o app,
o CORS, os arquivos estáticos e as rotas raiz (index.html/favicon).
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import auth_service as auth
import db_conexao
import frete_db as db
import frete_service as fs
import geo_service as geo
from routers import admin_banco, admin_precos, admin_usuarios, historico, orcamento, parametros
from routers import auth as auth_router
from routers import geo as geo_router

BASE_DIR = Path(__file__).resolve().parent
INDEX_PATH = BASE_DIR / "index.html"
ASSETS_DIR = BASE_DIR / "assets"
FAVICON_PATH = ASSETS_DIR / "favicon-16x16.png"

# Origens permitidas por CORS — por padrão só a própria API local (a UI é
# servida pelo próprio FastAPI, então na prática não depende de CORS pra
# funcionar; isso só importa se algo externo consumir a API do navegador).
# Configurável via CORS_ORIGINS (lista separada por vírgula) para quem
# rodar a API numa porta/host diferente do padrão.
_CORS_ORIGINS_PADRAO = "http://localhost:8000,http://127.0.0.1:8000"
CORS_ORIGINS = [
    origem.strip()
    for origem in os.environ.get("CORS_ORIGINS", _CORS_ORIGINS_PADRAO).split(",")
    if origem.strip()
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()  # garante que o banco/tabelas existem (não sobrescreve dados) — só roda aqui, uma vez
    fs.carregar_parametros()
    auth.garantir_usuario_padrao()
    yield


app = FastAPI(
    title="API de Orçamento de Frete",
    description="Calcula o frete a partir das regras cadastradas no banco frete.db",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,  # necessário pro cookie de sessão de login
    allow_methods=["*"],
    allow_headers=["*"],
)

if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")

app.include_router(auth_router.router)
app.include_router(geo_router.router)
app.include_router(orcamento.router)
app.include_router(historico.router)
app.include_router(parametros.router)
app.include_router(admin_precos.router)
app.include_router(admin_usuarios.router)
app.include_router(admin_banco.router)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    if not FAVICON_PATH.exists():
        raise HTTPException(status_code=404, detail="Favicon nao encontrado.")
    return FileResponse(FAVICON_PATH)


@app.get("/", include_in_schema=False)
@app.get("/orçamentos", include_in_schema=False)
def raiz():
    if not INDEX_PATH.exists():
        raise HTTPException(status_code=500, detail="Arquivo index.html não encontrado.")
    return FileResponse(INDEX_PATH)


@app.get("/api/status", tags=["Status"])
def status():
    cfg = db_conexao.config_sem_senha()
    if cfg["tipo"] == "sqlite":
        banco = cfg.get("sqlite_path") or db.DB_PATH
    else:
        banco = f"{cfg['tipo']}://{cfg.get('host', '')}/{cfg.get('banco', '')}"
    return {
        "status": "ok",
        "servico": "API de Orçamento de Frete",
        "versao": app.version,
        "banco": banco,
        "banco_tipo": cfg["tipo"],
        "geo_provider": "google" if geo.usando_google() else "osm",
    }


@app.get("/health", tags=["Status"])
def health():
    return {"status": "ok"}


_HOSTS_LOCAIS = {"127.0.0.1", "localhost", "::1"}


if __name__ == "__main__":
    import sys

    import uvicorn

    # Por padrão só escuta em localhost — evita expor a API (e o login) pra
    # rede sem querer. Quem precisar acessar de outra máquina na rede local
    # define HOST=0.0.0.0 explicitamente (ex: variável de ambiente no
    # iniciar_api.bat).
    host = os.environ.get("HOST", "127.0.0.1")
    ssl_keyfile = os.environ.get("SSL_KEYFILE") or None
    ssl_certfile = os.environ.get("SSL_CERTFILE") or None

    if bool(ssl_keyfile) != bool(ssl_certfile):
        sys.exit("Erro: SSL_KEYFILE e SSL_CERTFILE precisam ser definidos juntos (só um dos dois foi passado).")

    # Fora de localhost, login e cookie de sessão trafegam pela rede — sem
    # TLS isso vai em texto puro. Em vez de deixar passar sem avisar,
    # recusa subir até alguém configurar um certificado (autoassinado pra
    # uso interno, ou via proxy reverso como Caddy/nginx na frente, caso em
    # que a própria API pode continuar em HTTP e receber HOST=127.0.0.1).
    if host not in _HOSTS_LOCAIS and not ssl_keyfile:
        sys.exit(
            f"Erro: HOST={host!r} expõe a API fora desta máquina, mas nenhum certificado TLS foi configurado.\n"
            "Defina SSL_KEYFILE e SSL_CERTFILE (variáveis de ambiente) antes de subir a API assim, "
            "ou coloque um proxy reverso com TLS na frente e mantenha HOST=127.0.0.1 aqui."
        )

    uvicorn.run(
        "main:app", host=host, port=8000, reload=True,
        ssl_keyfile=ssl_keyfile, ssl_certfile=ssl_certfile,
    )
