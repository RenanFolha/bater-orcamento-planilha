# Desenvolvedor Chefe: RenanFolha

"""
Testes de db_conexao.py: a camada fina que permite trocar o banco de
SQLite pra SQL Server/MySQL/PostgreSQL (ver routers/admin_banco.py).

Não há SQL Server/MySQL/PostgreSQL disponíveis neste ambiente — os
testes daqui cobrem a lógica que dá pra verificar sem um servidor de
verdade: tradução de placeholder "?" pro paramstyle de cada driver
(usando um stub DB-API fake, não o driver real), o wrapper de linha por
dict, config em disco, e o round-trip completo de exportar/importar
todas as tabelas usando dois bancos SQLite temporários (prova a ordem
seguro de FK sem depender de nada externo).
"""

import json
import sqlite3
import sys

import pytest

import auth_service as auth
import db_conexao
import frete_db as db

# ============================================================
# _traduzir_placeholders
# ============================================================

def test_traduzir_placeholders_qmark_nao_muda():
    sql = "SELECT * FROM x WHERE a = ? AND b = ?"
    assert db_conexao._traduzir_placeholders(sql, "qmark") == sql


@pytest.mark.parametrize("paramstyle", ["format", "pyformat"])
def test_traduzir_placeholders_troca_por_percent_s(paramstyle):
    sql = "SELECT * FROM x WHERE a = ? AND b = ?"
    assert db_conexao._traduzir_placeholders(sql, paramstyle) == "SELECT * FROM x WHERE a = %s AND b = %s"


# ============================================================
# _montar_linha / _CursorAdaptado / _ConexaoAdaptada — com um stub
# DB-API fake (paramstyle "format", como pymysql), sem precisar de
# nenhum driver de verdade instalado.
# ============================================================

class _CursorFake:
    def __init__(self, tabela):
        self._tabela = tabela
        self.description = None
        self.lastrowid = None
        self._resultado = []

    def execute(self, sql, params):
        assert "?" not in sql, "placeholder deveria ter sido traduzido antes de chegar aqui"
        if sql.startswith("SELECT"):
            self.description = [("id",), ("nome",)]
            self._resultado = list(self._tabela)
        elif sql.startswith("INSERT"):
            novo_id = len(self._tabela) + 1
            self._tabela.append((novo_id, params[0]))
            self.lastrowid = novo_id

    def executemany(self, sql, lista_params):
        assert "?" not in sql, "placeholder deveria ter sido traduzido antes de chegar aqui"
        for params in lista_params:
            novo_id = len(self._tabela) + 1
            self._tabela.append((novo_id, params[0]))

    def fetchone(self):
        return self._resultado[0] if self._resultado else None

    def fetchall(self):
        return self._resultado


class _ConexaoFake:
    """Simula uma conexão DB-API com paramstyle "format" (%s), como
    pymysql -- suficiente pra exercitar _ConexaoAdaptada sem o driver
    de verdade."""
    def __init__(self):
        self._tabela = []
        self.commits = 0
        self.fechada = False

    def cursor(self):
        return _CursorFake(self._tabela)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        self.fechada = True


def test_conexao_adaptada_traduz_placeholder_e_devolve_linha_dict():
    nativa = _ConexaoFake()
    adaptada = db_conexao._ConexaoAdaptada(nativa, paramstyle="format")

    cur = adaptada.execute("INSERT INTO x (nome) VALUES (?)", ("Teste",))
    assert cur.lastrowid == 1

    cur2 = adaptada.execute("SELECT * FROM x WHERE nome = ?", ("Teste",))
    linhas = cur2.fetchall()
    assert len(linhas) == 1
    assert linhas[0]["id"] == 1
    assert linhas[0]["nome"] == "Teste"
    assert dict(linhas[0]) == {"id": 1, "nome": "Teste"}

    cur3 = adaptada.execute("SELECT * FROM x WHERE nome = ?", ("Teste",))
    linha_unica = cur3.fetchone()
    assert linha_unica["id"] == 1
    assert linha_unica["nome"] == "Teste"


def test_conexao_adaptada_commit_e_close_repassam_pra_nativa():
    nativa = _ConexaoFake()
    adaptada = db_conexao._ConexaoAdaptada(nativa, paramstyle="format")
    adaptada.commit()
    adaptada.close()
    assert nativa.commits == 1
    assert nativa.fechada is True


def test_conexao_adaptada_rollback_repassa_pra_nativa():
    class _NativaComRollback(_ConexaoFake):
        def __init__(self):
            super().__init__()
            self.rollbacks = 0

        def rollback(self):
            self.rollbacks += 1

    nativa = _NativaComRollback()
    db_conexao._ConexaoAdaptada(nativa, paramstyle="format").rollback()
    assert nativa.rollbacks == 1


def test_conexao_adaptada_executemany_traduz_placeholder():
    nativa = _ConexaoFake()
    adaptada = db_conexao._ConexaoAdaptada(nativa, paramstyle="format")
    adaptada.executemany("INSERT INTO x (nome) VALUES (?)", [("A",), ("B",)])
    assert [row[1] for row in nativa._tabela] == ["A", "B"]


def test_cursor_adaptado_fetchone_sem_description_devolve_cru():
    # UPDATE/INSERT/DELETE não tem description (não é um SELECT) --
    # fetchone() nesse caso só repassa o que o driver devolveu (geralmente
    # None), sem tentar montar uma linha por nome de coluna.
    class _CursorSemDescription:
        description = None

        def fetchone(self):
            return None

        def fetchall(self):
            return []

    cursor = db_conexao._CursorAdaptado(_CursorSemDescription())
    assert cursor.fetchone() is None
    assert cursor.fetchall() == []


def test_conexao_adaptada_executescript_separa_por_ponto_e_virgula():
    # executescript passa cada trecho pro cursor com um único argumento
    # (sem params) -- diferente de execute()/executemany(), que sempre
    # recebem parâmetros junto.
    comandos_executados = []

    class _CursorExecuteScript:
        def execute(self, sql):
            comandos_executados.append(sql)

    class _NativaExecuteScript:
        def cursor(self):
            return _CursorExecuteScript()

    adaptada = db_conexao._ConexaoAdaptada(_NativaExecuteScript(), paramstyle="format")
    adaptada.executescript("CREATE TABLE x (id INT);  \n  CREATE TABLE y (id INT); ;  ")
    # trechos vazios (entre ";;" ou nas pontas) são ignorados
    assert comandos_executados == ["CREATE TABLE x (id INT)", "CREATE TABLE y (id INT)"]


def test_cursor_adaptado_iteravel():
    class _CursorComDados:
        description = [("id",), ("nome",)]

        def fetchall(self):
            return [(1, "A"), (2, "B")]

        def fetchone(self):
            return (1, "A")

    cursor = db_conexao._CursorAdaptado(_CursorComDados())
    nomes = [linha["nome"] for linha in cursor]
    assert nomes == ["A", "B"]


# ============================================================
# _cifrar_senha / _decifrar_senha
# ============================================================


def test_cifrar_e_decifrar_senha_vazia_nao_chama_fernet():
    assert db_conexao._cifrar_senha("") == ""
    assert db_conexao._decifrar_senha("") == ""


# ============================================================
# Config em disco (db_config.json)
# ============================================================

def test_carregar_config_sem_arquivo_devolve_padrao_sqlite(tmp_path, monkeypatch):
    monkeypatch.setattr(db_conexao, "DB_CONFIG_PATH", str(tmp_path / "nao_existe.json"))
    cfg = db_conexao.carregar_config()
    assert cfg["tipo"] == "sqlite"
    assert cfg["sqlite_path"] == ""


def test_salvar_e_carregar_config(tmp_path, monkeypatch):
    caminho = tmp_path / "db_config.json"
    monkeypatch.setattr(db_conexao, "DB_CONFIG_PATH", str(caminho))
    monkeypatch.setattr(db_conexao, "DB_CONFIG_KEY_PATH", str(tmp_path / "db_config.key"))

    db_conexao.salvar_config({
        "tipo": "postgresql", "host": "meuserver", "porta": 5432,
        "banco": "frete", "usuario": "admin", "senha": "segredo",
    })
    cfg = db_conexao.carregar_config()
    assert cfg["tipo"] == "postgresql"
    assert cfg["host"] == "meuserver"
    assert cfg["senha"] == "segredo"

    # a senha grava cifrada em disco (Fernet, chave local em
    # DB_CONFIG_KEY_PATH) -- nunca em texto puro, ver docstring do módulo
    bruto = json.loads(caminho.read_text(encoding="utf-8"))
    assert bruto["senha"] != "segredo"
    assert bruto["senha"] != ""


def test_carregar_config_aceita_senha_em_texto_puro_de_versao_antiga(tmp_path, monkeypatch):
    """db_config.json gravado por uma versão anterior a essa mudança
    ainda tem a senha em texto puro -- carregar_config precisa continuar
    lendo esse valor (a próxima salvar_config já regrava cifrado)."""
    caminho = tmp_path / "db_config.json"
    caminho.write_text(json.dumps({"tipo": "mysql", "senha": "texto-puro-antigo"}), encoding="utf-8")
    monkeypatch.setattr(db_conexao, "DB_CONFIG_PATH", str(caminho))
    monkeypatch.setattr(db_conexao, "DB_CONFIG_KEY_PATH", str(tmp_path / "db_config.key"))

    cfg = db_conexao.carregar_config()
    assert cfg["senha"] == "texto-puro-antigo"


def test_conectar_sqlite_sem_caminho_da_erro():
    cfg = {"tipo": "sqlite", "sqlite_path": ""}
    with pytest.raises(db_conexao.ErroConexaoBanco, match="Caminho"):
        db_conexao.conectar(cfg, sqlite_path_padrao=None)


@pytest.mark.parametrize("tipo,driver,trecho_esperado", [
    ("sqlserver", "pyodbc", "SQL Server"),
    ("mysql", "pymysql", "MySQL"),
    ("postgresql", "psycopg2", "PostgreSQL"),
])
def test_conectar_com_driver_instalado_mas_servidor_inacessivel_da_erro_amigavel(tipo, driver, trecho_esperado):
    # Complementa test_conectar_sem_driver_instalado_da_erro_amigavel
    # (que só roda quando o driver NÃO está instalado): aqui é o
    # contrário -- só roda quando o driver ESTÁ instalado (caso deste
    # ambiente, ver requirements.txt), tentando conectar de verdade num
    # host que recusa a conexão na hora (porta 1, ninguém escuta) --
    # cobre o `except <driver>.Error` de cada dialeto sem precisar de um
    # servidor real no ar, só que o driver saiba dizer "não consegui".
    import importlib
    try:
        importlib.import_module(driver)
    except ImportError:
        pytest.skip(f"{driver} não está instalado neste ambiente")

    cfg = {"tipo": tipo, "host": "127.0.0.1", "porta": 1, "banco": "x", "usuario": "x", "senha": "x"}
    with pytest.raises(db_conexao.ErroConexaoBanco, match=trecho_esperado):
        db_conexao.conectar(cfg)


@pytest.mark.parametrize("tipo,driver", [
    ("sqlserver", "pyodbc"), ("mysql", "pymysql"), ("postgresql", "psycopg2"),
])
def test_conectar_sem_driver_instalado_da_erro_amigavel(tipo, driver):
    # Neste ambiente nenhum dos três drivers está instalado -- exercita
    # de verdade o fallback de ImportError (não um mock). Se o driver
    # estiver instalado (ambiente diferente), o teste não se aplica --
    # pula em vez de tentar conectar num servidor de verdade.
    import importlib
    try:
        importlib.import_module(driver)
    except ImportError:
        pass
    else:
        pytest.skip(f"{driver} está instalado neste ambiente — o teste de driver ausente não se aplica")

    cfg = {"tipo": tipo, "host": "x", "porta": 1, "banco": "x", "usuario": "x", "senha": "x"}
    with pytest.raises(db_conexao.ErroConexaoBanco, match=driver):
        db_conexao.conectar(cfg)


@pytest.mark.parametrize("tipo,driver", [
    ("sqlserver", "pyodbc"), ("mysql", "pymysql"), ("postgresql", "psycopg2"),
])
def test_conectar_sem_driver_instalado_via_sys_modules(tipo, driver, monkeypatch):
    # Complementa test_conectar_sem_driver_instalado_da_erro_amigavel (que
    # só roda quando o driver de fato não está instalado neste ambiente):
    # aqui força o ImportError via sys.modules[driver] = None (truque
    # padrão do CPython -- faz "import <driver>" levantar ImportError
    # mesmo com o pacote instalado), rodando sempre, em qualquer ambiente.
    monkeypatch.setitem(sys.modules, driver, None)
    cfg = {"tipo": tipo, "host": "x", "porta": 1, "banco": "x", "usuario": "x", "senha": "x"}
    with pytest.raises(db_conexao.ErroConexaoBanco, match=driver):
        db_conexao.conectar(cfg)


@pytest.mark.parametrize("tipo,driver", [
    ("sqlserver", "pyodbc"), ("mysql", "pymysql"), ("postgresql", "psycopg2"),
])
def test_conectar_sucesso_devolve_conexao_adaptada(tipo, driver, monkeypatch):
    # Mocka connect() do driver de baixo nível pra simular uma conexão
    # bem-sucedida sem precisar de um servidor de verdade -- cobre o
    # `return _ConexaoAdaptada(...)` de cada dialeto.
    modulo = pytest.importorskip(driver)

    class _NativaFake:
        pass

    nativa_fake = _NativaFake()
    monkeypatch.setattr(modulo, "connect", lambda *args, **kwargs: nativa_fake)

    cfg = {"tipo": tipo, "host": "x", "porta": 1, "banco": "x", "usuario": "x", "senha": "x"}
    conn = db_conexao.conectar(cfg)
    assert isinstance(conn, db_conexao._ConexaoAdaptada)
    assert conn._conexao is nativa_fake
    assert conn._paramstyle == modulo.paramstyle


def test_conectar_tipo_desconhecido_da_erro():
    with pytest.raises(db_conexao.ErroConexaoBanco, match="desconhecido"):
        db_conexao.conectar({"tipo": "banco-que-nao-existe"})


def test_erros_integridade_nativos_ignora_driver_nao_instalado(monkeypatch):
    monkeypatch.setitem(sys.modules, "pyodbc", None)
    monkeypatch.setitem(sys.modules, "pymysql", None)
    monkeypatch.setitem(sys.modules, "psycopg2", None)
    assert db_conexao._erros_integridade_nativos() == (sqlite3.IntegrityError,)


def test_config_sem_senha_nunca_ecoa_a_senha():
    cfg = {"tipo": "mysql", "host": "x", "senha": "segredo"}
    seguro = db_conexao.config_sem_senha(cfg)
    assert "senha" not in seguro
    assert seguro["senha_configurada"] is True

    cfg_sem_senha = {"tipo": "sqlite", "senha": ""}
    assert db_conexao.config_sem_senha(cfg_sem_senha)["senha_configurada"] is False


# ============================================================
# Exportar/importar todas as tabelas — round-trip entre dois SQLite
# temporários (prova a ordem de FK sem precisar de servidor nenhum).
# ============================================================

def test_exportar_importar_todas_tabelas_round_trip(tmp_path, monkeypatch):
    origem = tmp_path / "origem.db"
    destino = tmp_path / "destino.db"

    monkeypatch.setattr(db, "DB_PATH", str(origem))
    monkeypatch.setattr(db_conexao, "DB_CONFIG_PATH", str(tmp_path / "nao_existe.json"))
    db.init_db()  # cria e semeia a origem com os dados de exemplo padrão
    auth.garantir_usuario_padrao()  # mesma sequência de boot do main.py (lifespan)

    with db.get_connection() as conn:
        dados = db_conexao.exportar_todas_tabelas(conn)

    assert dados["filiais"], "a origem deveria ter os dados de exemplo (filiais) semeados por init_db"
    assert "usuarios" in dados and dados["usuarios"], "usuário admin padrão deveria ter sido criado"

    # cria o schema (vazio) no destino, sem semear dados de exemplo --
    # importar_todas_tabelas assume destino vazio (ver docstring)
    monkeypatch.setattr(db, "DB_PATH", str(destino))
    db.init_db()
    with db.get_connection() as conn:
        for tabela in db_conexao.ORDEM_TABELAS:
            conn.execute(f"DELETE FROM {tabela}")

    with db.get_connection() as conn:
        resultado = db_conexao.importar_todas_tabelas(conn, dados)

    assert resultado["filiais"] == len(dados["filiais"])
    assert resultado["usuarios"] == len(dados["usuarios"])

    with db.get_connection() as conn:
        dados_destino = db_conexao.exportar_todas_tabelas(conn)
    for tabela in db_conexao.ORDEM_TABELAS:
        assert len(dados_destino[tabela]) == len(dados[tabela]), f"contagem diferente em {tabela}"
