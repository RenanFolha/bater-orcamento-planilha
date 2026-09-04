# Desenvolvedor Chefe: RenanFolha

"""
Testes do schema consolidado pros dialetos não-SQLite (ver
frete_db._gerar_schema_consolidado) -- não há SQL Server/MySQL/
PostgreSQL disponíveis neste ambiente pra validar de verdade, mas dá pra
conferir a estrutura (uma tabela por nome esperado, sem sobrar token
{PK}) e, trocando {PK} pela sintaxe do próprio SQLite, confirmar que o
SQL gerado é sintaticamente válido (pega erro de digitação/vírgula
faltando, mesmo sem substituir pelo dialeto real).
"""

import sqlite3

import pytest

import db_conexao
import frete_db as db


@pytest.mark.parametrize("tipo", ["sqlserver", "mysql", "postgresql"])
def test_gerar_schema_consolidado_sem_token_sobrando(tipo):
    sql = db._gerar_schema_consolidado(tipo)
    assert "{PK}" not in sql
    assert db._PK_DDL_POR_DIALETO[tipo] in sql


@pytest.mark.parametrize("tipo", ["sqlserver", "mysql", "postgresql"])
def test_gerar_schema_consolidado_tem_todas_as_tabelas(tipo):
    sql = db._gerar_schema_consolidado(tipo)
    for tabela in db_conexao.ORDEM_TABELAS:
        assert f"CREATE TABLE {tabela} (" in sql, f"tabela {tabela} não encontrada no schema consolidado"


def test_schema_consolidado_e_sql_sintaticamente_valido():
    """Troca {PK} pela sintaxe do SQLite (só pra validar a sintaxe base,
    já que aqui não tem outro motor disponível) e roda executescript de
    verdade -- typo ou vírgula faltando derruba esse teste."""
    sql = db.SCHEMA_CONSOLIDADO_TEMPLATE.replace("{PK}", "INTEGER PRIMARY KEY AUTOINCREMENT")
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(sql)
        tabelas = {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()
    for tabela in db_conexao.ORDEM_TABELAS:
        assert tabela in tabelas
