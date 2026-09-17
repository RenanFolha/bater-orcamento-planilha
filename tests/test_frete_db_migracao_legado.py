# Desenvolvedor Chefe: RenanFolha

"""
Testes de frete_db._migrar_colunas e _completar_carreta_fechada: rodam
uma vez, na inicialização, pra atualizar um banco criado por uma versão
anterior do sistema (colunas/tabelas que não existiam ainda) sem apagar
nada do que já estava cadastrado. Usa `tmp_path` (não `banco_temporario`,
que já cria o schema atual) pra montar um SQLite com o formato antigo do
zero.
"""

import sqlite3

import db_conexao
import frete_db as db


def _banco_legado(caminho: str) -> sqlite3.Connection:
    conn = sqlite3.connect(caminho)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE faixas_peso (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            de REAL NOT NULL, ate REAL NOT NULL, tarifa_base REAL NOT NULL,
            custo_kg_adicional REAL NOT NULL DEFAULT 0, observacao TEXT DEFAULT ''
        );
        CREATE TABLE faixas_distancia (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            de REAL NOT NULL, ate REAL NOT NULL, taxa_fixa REAL NOT NULL,
            tarifa_km REAL NOT NULL DEFAULT 0, observacao TEXT DEFAULT ''
        );
        CREATE TABLE parametros_gerais (id INTEGER PRIMARY KEY, frete_minimo REAL);
        CREATE TABLE coleta_cidades_fixas (
            id INTEGER PRIMARY KEY AUTOINCREMENT, cidade TEXT NOT NULL, valor_fixo REAL NOT NULL
        );
        CREATE TABLE filiais (
            id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, endereco TEXT NOT NULL,
            latitude REAL, longitude REAL
        );
        CREATE TABLE veiculos (
            id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, tarifa_km REAL NOT NULL,
            valor_kg_excedente REAL NOT NULL DEFAULT 0, peso_incluso_kg REAL NOT NULL DEFAULT 0
        );
        CREATE TABLE orcamentos_historico (
            id INTEGER PRIMARY KEY AUTOINCREMENT, codigo TEXT NOT NULL
        );
        CREATE TABLE usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL
        );
        CREATE TABLE escalas_obrigatorias (
            id INTEGER PRIMARY KEY AUTOINCREMENT, cidade_origem TEXT NOT NULL,
            cidade_destino TEXT NOT NULL, filial_escala TEXT NOT NULL, observacao TEXT DEFAULT ''
        );
        CREATE TABLE prioridades_rota (
            id INTEGER PRIMARY KEY AUTOINCREMENT, estado_origem TEXT NOT NULL,
            cidade_destino TEXT NOT NULL, filial_escala TEXT NOT NULL, observacao TEXT DEFAULT '',
            UNIQUE(estado_origem, cidade_destino)
        );
        INSERT INTO escalas_obrigatorias (cidade_origem, cidade_destino, filial_escala)
            VALUES ('SP', 'Manaus', 'Belem');
    """)
    conn.commit()
    return conn


def test_migrar_colunas_atualiza_banco_de_versao_anterior(tmp_path):
    conn = _banco_legado(str(tmp_path / "banco_antigo.db"))

    db._migrar_colunas(conn)
    conn.commit()

    # tipo_frete adicionada nas duas tabelas antigas
    assert db._coluna_existe(conn, "faixas_peso", "tipo_frete")
    assert db._coluna_existe(conn, "faixas_distancia", "tipo_frete")

    # parametros_gerais removida (frete mínimo/seguro/imposto não existem mais)
    tabela_removida = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='parametros_gerais'"
    ).fetchone()
    assert tabela_removida is None

    # coleta_cidades_fixas recriada no formato novo (filial_origem + veiculo)
    assert db._coluna_existe(conn, "coleta_cidades_fixas", "filial_origem")
    assert db._coluna_existe(conn, "coleta_cidades_fixas", "veiculo")

    # filiais ganha uf
    assert db._coluna_existe(conn, "filiais", "uf")

    # veiculos: colunas novas adicionadas, coluna renomeada e coluna removida
    for coluna in (
        "de", "ate", "tarifa_km_retorno", "tarifa_km_manutencao",
        "capacidade_m3", "percentual_capacidade_util", "numero_eixos", "valor_tonelada_excedente",
    ):
        assert db._coluna_existe(conn, "veiculos", coluna), f"coluna {coluna} não foi adicionada"
    assert not db._coluna_existe(conn, "veiculos", "valor_kg_excedente")
    assert not db._coluna_existe(conn, "veiculos", "peso_incluso_kg")

    # orcamentos_historico.criado_por e usuarios.deve_trocar_senha adicionadas
    assert db._coluna_existe(conn, "orcamentos_historico", "criado_por")
    assert db._coluna_existe(conn, "usuarios", "deve_trocar_senha")

    # escalas_obrigatorias migrada pra prioridades_rota (dado preservado) e removida
    linhas = conn.execute(
        "SELECT estado_origem, cidade_destino, filial_escala FROM prioridades_rota"
    ).fetchall()
    assert ("SP", "Manaus", "Belem") in [tuple(r) for r in linhas]
    tabela_antiga = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='escalas_obrigatorias'"
    ).fetchone()
    assert tabela_antiga is None

    conn.close()


def test_migrar_colunas_e_idempotente(tmp_path):
    # Rodar duas vezes seguidas (ex: reiniciar a API várias vezes) não
    # pode falhar tentando adicionar uma coluna que já existe.
    conn = _banco_legado(str(tmp_path / "banco_antigo2.db"))
    db._migrar_colunas(conn)
    conn.commit()
    db._migrar_colunas(conn)  # não deve levantar exceção
    conn.commit()
    conn.close()


def test_completar_carreta_fechada_insere_exemplo_quando_ausente(banco_temporario):
    with db.get_connection() as conn:
        conn.execute("DELETE FROM faixas_peso WHERE tipo_frete = 'Carreta Fechada'")
        conn.execute("DELETE FROM faixas_distancia WHERE tipo_frete = 'Carreta Fechada'")
        db._completar_carreta_fechada(conn)
        peso = conn.execute(
            "SELECT COUNT(*) FROM faixas_peso WHERE tipo_frete = 'Carreta Fechada'"
        ).fetchone()[0]
        distancia = conn.execute(
            "SELECT COUNT(*) FROM faixas_distancia WHERE tipo_frete = 'Carreta Fechada'"
        ).fetchone()[0]
    assert peso == 3
    assert distancia == 3


def test_init_db_usa_schema_consolidado_para_tipo_nao_sqlite(monkeypatch):
    # init_db() com um banco de destino != sqlite (SQL Server/MySQL/
    # PostgreSQL) pula o SCHEMA + _migrar_colunas (só faz sentido pra
    # SQLite, que acumulou a cadeia histórica de ALTER TABLE) e cria tudo
    # já no formato final via _gerar_schema_consolidado. Mocka conectar()
    # e o seed (testados à parte) pra isolar só esse ramo de init_db().
    class _ConexaoFake:
        def __init__(self):
            self.scripts_executados = []

        def executescript(self, script):
            self.scripts_executados.append(script)

        def commit(self):
            pass

        def close(self):
            pass

    conexao_fake = _ConexaoFake()
    monkeypatch.setattr(db_conexao, "carregar_config", lambda: {"tipo": "mysql"})
    monkeypatch.setattr(db_conexao, "conectar", lambda *args, **kwargs: conexao_fake)
    monkeypatch.setattr(db, "_seed_se_vazio", lambda conn: None)
    monkeypatch.setattr(db, "_completar_carreta_fechada", lambda conn: None)

    db.init_db()

    assert len(conexao_fake.scripts_executados) == 1
    assert conexao_fake.scripts_executados[0] == db._gerar_schema_consolidado("mysql")


def test_completar_carreta_fechada_nao_duplica_quando_ja_existe(banco_temporario):
    with db.get_connection() as conn:
        antes = conn.execute(
            "SELECT COUNT(*) FROM faixas_peso WHERE tipo_frete = 'Carreta Fechada'"
        ).fetchone()[0]
        assert antes > 0  # seed padrão já cadastra
        db._completar_carreta_fechada(conn)  # não deve inserir de novo
        depois = conn.execute(
            "SELECT COUNT(*) FROM faixas_peso WHERE tipo_frete = 'Carreta Fechada'"
        ).fetchone()[0]
    assert depois == antes
