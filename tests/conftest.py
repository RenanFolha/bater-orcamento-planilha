import sys
from pathlib import Path

# frete_service.py, frete_db.py etc. vivem na raiz do projeto (não são um
# pacote instalável) — garante que a raiz esteja no sys.path independente
# de rootdir/importmode do pytest.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import auth_service as auth
import frete_db as db


@pytest.fixture(autouse=True)
def _tentativas_login_limpas():
    """auth_service guarda as tentativas de login falhas num dict global do
    processo (de propósito — é o contador de rate limit, ver auth_service.py),
    não no banco. Sem isso, um teste que exercite o bloqueio (ou vários
    logins errados em sequência) deixaria outros testes bloqueados por
    tabela cruzada de identificador (IP/username) mesmo usando bancos
    temporários diferentes."""
    auth._tentativas_login.clear()
    yield
    auth._tentativas_login.clear()


@pytest.fixture
def banco_temporario(tmp_path, monkeypatch):
    """Aponta frete_db para um arquivo SQLite novo e isolado (num diretório
    temporário do pytest) e roda o schema completo nele. Usado por qualquer
    teste que precise gravar/ler no banco de verdade (auth, histórico, API)
    sem tocar no frete.db do ambiente nem vazar estado entre testes.

    Funciona monkeypatchando o atributo de módulo `frete_db.DB_PATH`: como
    get_connection() lê esse nome do escopo do módulo a cada chamada (não
    captura o valor num default), qualquer código que chame `db.get_connection()`
    — mesmo em auth_service.py ou main.py, que importam `frete_db as db`
    separadamente — enxerga o caminho trocado."""
    caminho = tmp_path / "teste_frete.db"
    monkeypatch.setattr(db, "DB_PATH", str(caminho))
    db.init_db()
    return caminho
