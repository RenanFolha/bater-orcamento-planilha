# Desenvolvedor Chefe: RenanFolha

"""
Testes de coleta_cidades_fixas (frete_db.py): uma linha agora pode cobrir
uma lista de cidades (separadas por vírgula) em vez de só uma, e a
migração do schema antigo (UNIQUE por cidade única) precisa preservar os
dados já cadastrados. Usa o fixture `banco_temporario` (conftest.py) —
nunca toca no frete.db real.
"""

import sqlite3

import pytest

import frete_db as db


def test_busca_encontra_qualquer_cidade_da_lista(banco_temporario):
    db.inserir_coleta_cidade_fixa("São Paulo", "Osasco, Barueri, Cotia", "VUC", 80.0)

    for cidade in ("Osasco", "Barueri", "Cotia", "osasco", "COTIA"):
        achado = db.buscar_coleta_cidade_fixa("São Paulo", cidade, "VUC")
        assert achado is not None
        assert achado["valor_fixo"] == 80.0

    assert db.buscar_coleta_cidade_fixa("São Paulo", "Santana de Parnaíba", "VUC") is None


def test_cidade_repetida_no_mesmo_filial_veiculo_da_conflito(banco_temporario):
    db.inserir_coleta_cidade_fixa("São Paulo", "Osasco, Barueri", "VUC", 80.0)
    with pytest.raises(sqlite3.IntegrityError, match="Barueri"):
        db.inserir_coleta_cidade_fixa("São Paulo", "Barueri, Cotia", "VUC", 90.0)


def test_mesma_cidade_em_veiculo_diferente_nao_conflita(banco_temporario):
    db.inserir_coleta_cidade_fixa("São Paulo", "Osasco", "VUC", 80.0)
    # mesmo filial+cidade, mas veículo diferente -> linha independente, sem conflito
    id2 = db.inserir_coleta_cidade_fixa("São Paulo", "Osasco", "Carreta", 150.0)
    assert id2 is not None
    assert db.buscar_coleta_cidade_fixa("São Paulo", "Osasco", "VUC")["valor_fixo"] == 80.0
    assert db.buscar_coleta_cidade_fixa("São Paulo", "Osasco", "Carreta")["valor_fixo"] == 150.0


def test_atualizar_permite_manter_as_mesmas_cidades(banco_temporario):
    id_ = db.inserir_coleta_cidade_fixa("São Paulo", "Osasco, Barueri", "VUC", 80.0)
    # reeditar a própria linha com as mesmas cidades (+ uma nova) não deve conflitar consigo mesma
    db.atualizar_coleta_cidade_fixa(id_, "São Paulo", "Osasco, Barueri, Cotia", "VUC", 85.0)
    achado = db.buscar_coleta_cidade_fixa("São Paulo", "Cotia", "VUC")
    assert achado["valor_fixo"] == 85.0


def test_atualizar_com_cidade_de_outra_linha_da_conflito(banco_temporario):
    db.inserir_coleta_cidade_fixa("São Paulo", "Osasco", "VUC", 80.0)
    id2 = db.inserir_coleta_cidade_fixa("São Paulo", "Cotia", "VUC", 90.0)
    with pytest.raises(sqlite3.IntegrityError, match="Osasco"):
        db.atualizar_coleta_cidade_fixa(id2, "São Paulo", "Osasco", "VUC", 90.0)


def test_lista_vazia_e_rejeitada(banco_temporario):
    with pytest.raises(sqlite3.IntegrityError):
        db.inserir_coleta_cidade_fixa("São Paulo", "  ,  ,", "VUC", 80.0)


def test_migracao_do_schema_antigo_preserva_dados(banco_temporario):
    with db.get_connection() as conn:
        conn.execute("DROP TABLE coleta_cidades_fixas")
        conn.execute("""
            CREATE TABLE coleta_cidades_fixas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filial_origem TEXT NOT NULL,
                cidade_destino TEXT NOT NULL,
                veiculo TEXT NOT NULL,
                valor_fixo REAL NOT NULL,
                observacao TEXT DEFAULT '',
                UNIQUE(filial_origem, cidade_destino, veiculo)
            )
        """)
        conn.execute(
            "INSERT INTO coleta_cidades_fixas (filial_origem, cidade_destino, veiculo, valor_fixo, observacao) "
            "VALUES ('São Paulo', 'Osasco', 'VUC', 80.0, 'preço combinado')"
        )

    db.init_db()  # roda a migração de novo (idempotente pro resto do schema)

    achado = db.buscar_coleta_cidade_fixa("São Paulo", "Osasco", "VUC")
    assert achado is not None
    assert achado["valor_fixo"] == 80.0
    assert achado["observacao"] == "preço combinado"

    # o schema novo não tem mais a UNIQUE antiga -> dá pra cadastrar outra
    # cidade pro mesmo filial+veiculo numa linha separada sem erro
    id2 = db.inserir_coleta_cidade_fixa("São Paulo", "Barueri", "VUC", 95.0)
    assert id2 is not None
