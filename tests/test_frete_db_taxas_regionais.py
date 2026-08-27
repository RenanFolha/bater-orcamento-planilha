"""
Testes de taxas_regionais (frete_db.py): `cidade` guarda uma ou mais
cidades separadas por vírgula numa linha só (mesmo padrão de
coleta_cidades_fixas) — conflito é por cidade já coberta pela mesma
taxa (`nome`), não mais por linha inteira. Usa o fixture
`banco_temporario` (conftest.py) — nunca toca no frete.db real.
"""

import sqlite3

import pytest

import frete_db as db


def test_inserir_e_listar_taxa_regional(banco_temporario):
    id_ = db.inserir_taxa_regional("Manaus", "Zona Franca", "fixo", 50.0)
    assert id_ is not None
    linhas = db.listar_taxas_regionais_admin()
    assert len(linhas) == 1
    assert linhas[0]["cidade"] == "Manaus"
    assert linhas[0]["nome"] == "Zona Franca"


def test_inserir_lista_de_cidades_em_uma_linha(banco_temporario):
    id_ = db.inserir_taxa_regional("Manaus, Boa Vista", "Área de Risco", "fixo", 30.0)
    assert id_ is not None
    linha = db.listar_taxas_regionais_admin()[0]
    assert linha["cidade"] == "Manaus, Boa Vista"


def test_mesma_cidade_taxa_diferente_nao_conflita(banco_temporario):
    db.inserir_taxa_regional("Manaus", "Zona Franca", "fixo", 50.0)
    id2 = db.inserir_taxa_regional("Manaus", "Área de Risco", "fixo", 30.0)
    assert id2 is not None
    assert len(db.listar_taxas_regionais_admin()) == 2


def test_cidade_repetida_na_mesma_taxa_da_conflito(banco_temporario):
    db.inserir_taxa_regional("Manaus, Boa Vista", "Área de Risco", "fixo", 30.0)
    with pytest.raises(sqlite3.IntegrityError):
        db.inserir_taxa_regional("Boa Vista, Belém", "Área de Risco", "fixo", 30.0)


def test_cidade_repetida_case_insensitive_da_conflito(banco_temporario):
    db.inserir_taxa_regional("Manaus", "Zona Franca", "fixo", 50.0)
    with pytest.raises(sqlite3.IntegrityError):
        db.inserir_taxa_regional("MANAUS", "zona franca", "fixo", 60.0)


def test_atualizar_taxa_regional_pode_reusar_suas_proprias_cidades(banco_temporario):
    id_ = db.inserir_taxa_regional("Manaus, Boa Vista", "Área de Risco", "fixo", 30.0)
    db.atualizar_taxa_regional(id_, "Manaus, Boa Vista, Rio Branco", "Área de Risco", "fixo", 35.0, "reajuste")
    linha = db.listar_taxas_regionais_admin()[0]
    assert linha["cidade"] == "Manaus, Boa Vista, Rio Branco"
    assert linha["valor"] == 35.0
    assert linha["observacao"] == "reajuste"


def test_atualizar_taxa_regional_nao_pode_roubar_cidade_de_outra_linha(banco_temporario):
    db.inserir_taxa_regional("Manaus", "Área de Risco", "fixo", 30.0)
    id2 = db.inserir_taxa_regional("Belém", "Área de Risco", "fixo", 30.0)
    with pytest.raises(sqlite3.IntegrityError):
        db.atualizar_taxa_regional(id2, "Belém, Manaus", "Área de Risco", "fixo", 30.0)


def test_excluir_taxa_regional(banco_temporario):
    id_ = db.inserir_taxa_regional("Manaus", "Zona Franca", "fixo", 50.0)
    db.excluir_taxa_regional(id_)
    assert db.listar_taxas_regionais_admin() == []


def test_inserir_sem_cidade_da_erro(banco_temporario):
    with pytest.raises(sqlite3.IntegrityError):
        db.inserir_taxa_regional("   ", "Zona Franca", "fixo", 50.0)


def test_migracao_do_schema_antigo_preserva_linhas(banco_temporario):
    # simula um banco no schema anterior (com UNIQUE(cidade, nome) e uma
    # cidade por linha) e confirma que _migrar_taxas_regionais_lista
    # recria a tabela sem perder nenhuma linha nem trocar os ids.
    with db.get_connection() as conn:
        conn.execute("DROP TABLE taxas_regionais")
        conn.execute("""
            CREATE TABLE taxas_regionais (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cidade TEXT NOT NULL,
                nome TEXT NOT NULL,
                tipo TEXT NOT NULL DEFAULT 'fixo' CHECK (tipo IN ('fixo', 'percentual')),
                valor REAL NOT NULL,
                observacao TEXT DEFAULT '',
                UNIQUE(cidade, nome)
            )
        """)
        conn.execute(
            "INSERT INTO taxas_regionais (id, cidade, nome, tipo, valor, observacao) VALUES (1, 'Manaus', 'Zona Franca', 'fixo', 50.0, '')"
        )
        conn.execute(
            "INSERT INTO taxas_regionais (id, cidade, nome, tipo, valor, observacao) VALUES (2, 'Belém', 'Zona Franca', 'fixo', 40.0, '')"
        )
        conn.commit()

    with db.get_connection() as conn:
        db._migrar_taxas_regionais_lista(conn)
        conn.commit()

    linhas = db.listar_taxas_regionais_admin()
    assert len(linhas) == 2
    assert {(r["id"], r["cidade"]) for r in linhas} == {(1, "Manaus"), (2, "Belém")}

    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='taxas_regionais'"
        ).fetchone()
    assert "UNIQUE(cidade, nome)" not in (row["sql"] or "")
