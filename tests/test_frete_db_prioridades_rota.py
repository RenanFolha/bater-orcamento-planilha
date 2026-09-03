# Desenvolvedor Chefe: RenanFolha

"""
Testes de prioridades_rota (frete_db.py): a regra é direcional
(estado_origem, em UF -> cidade_destino) e a UNIQUE(estado_origem,
cidade_destino) é case-insensitive na aplicação, mesmo sendo
case-sensitive no SQLite. Usa o fixture `banco_temporario`
(conftest.py) -- nunca toca no frete.db real.
"""

import sqlite3

import pytest

import frete_db as db


def test_inserir_e_listar_prioridade_rota(banco_temporario):
    id_ = db.inserir_prioridade_rota("*", "Manaus", "Belém")
    assert id_ is not None
    linhas = db.listar_prioridades_rota_admin()
    assert len(linhas) == 1
    assert linhas[0]["estado_origem"] == "*"
    assert linhas[0]["cidade_destino"] == "Manaus"
    assert linhas[0]["filial_escala"] == "Belém"


def test_direcao_invertida_nao_conflita(banco_temporario):
    db.inserir_prioridade_rota("SP", "Manaus", "Belém")
    id2 = db.inserir_prioridade_rota("AM", "São Paulo", "Belém")
    assert id2 is not None


def test_mesma_rota_da_conflito(banco_temporario):
    db.inserir_prioridade_rota("sp", "Manaus", "Belem")
    with pytest.raises(sqlite3.IntegrityError):
        db.inserir_prioridade_rota("SP", "manaus", "Belem")  # case-insensitive


def test_atualizar_prioridade_rota(banco_temporario):
    id_ = db.inserir_prioridade_rota("*", "Manaus", "Belém")
    db.atualizar_prioridade_rota(id_, "*", "Manaus", "Ananindeua", "trocou a filial de escala")
    linha = db.listar_prioridades_rota_admin()[0]
    assert linha["filial_escala"] == "Ananindeua"
    assert linha["observacao"] == "trocou a filial de escala"


def test_excluir_prioridade_rota(banco_temporario):
    id_ = db.inserir_prioridade_rota("*", "Manaus", "Belém")
    db.excluir_prioridade_rota(id_)
    assert db.listar_prioridades_rota_admin() == []
