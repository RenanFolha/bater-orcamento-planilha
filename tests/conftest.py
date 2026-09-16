# Desenvolvedor Chefe: RenanFolha

import sys
from pathlib import Path

# frete_service.py, frete_db.py etc. vivem na raiz do projeto (não são um
# pacote instalável) — garante que a raiz esteja no sys.path independente
# de rootdir/importmode do pytest.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

import auth_service as auth
import db_conexao
import frete_db as db
import main


@pytest.fixture(autouse=True)
def _tentativas_login_limpas():
    """auth_service guarda as tentativas de login falhas num dict global do
    processo (de propósito — é o contador de rate limit, ver auth_service.py),
    não no banco. Sem isso, um teste que exercite o bloqueio (ou vários
    logins errados em sequência) deixaria outros testes bloqueados por
    tabela cruzada de identificador (IP/username) mesmo usando bancos
    temporários diferentes."""
    auth._tentativas_login.clear()
    auth._contadores_rate_limit.clear()
    yield
    auth._tentativas_login.clear()
    auth._contadores_rate_limit.clear()


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
    separadamente — enxerga o caminho trocado.

    Também monkeypatcha `db_conexao.DB_CONFIG_PATH` pra um arquivo que não
    existe: se a máquina que roda os testes já tiver configurado um banco
    externo de verdade pela tela "Banco de dados" (`db_config.json` na
    raiz do projeto), sem isso os testes tentariam conectar nesse banco
    externo em vez do SQLite temporário — inclusive escrevendo nele.
    `db_conexao.DB_CONFIG_KEY_PATH` (chave de criptografia da senha) segue
    o mesmo isolamento, pra nenhum teste que salve uma config com senha
    gerar/gravar essa chave na raiz real do projeto."""
    caminho = tmp_path / "teste_frete.db"
    monkeypatch.setattr(db, "DB_PATH", str(caminho))
    monkeypatch.setattr(db_conexao, "DB_CONFIG_PATH", str(tmp_path / "nao_existe_db_config.json"))
    monkeypatch.setattr(db_conexao, "DB_CONFIG_KEY_PATH", str(tmp_path / "nao_existe_db_config.key"))
    db.init_db()
    return caminho


@pytest.fixture
def client(banco_temporario):
    """TestClient da API (ver main.py) sobre o banco temporário isolado
    acima -- fixture compartilhada por qualquer teste de integração via
    HTTP (test_main_api.py, test_orcamento_fracionado.py,
    test_admin_precos_router.py etc.)."""
    with TestClient(main.app) as c:
        yield c


def _login(client, username="admin", senha="admin123"):
    """Faz login no `client` acima e devolve a resposta -- helper
    compartilhado pelos mesmos arquivos de teste que usam a fixture
    `client`."""
    r = client.post("/auth/login", json={"username": username, "senha": senha})
    assert r.status_code == 200, r.text
    return r
