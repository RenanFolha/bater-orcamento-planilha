# Desenvolvedor Chefe: RenanFolha

"""
Testes de transportes (frete_db.py): `nome` é UNIQUE (case-sensitive).
`init_db()` já popula o banco com transportes de exemplo (ver
_seed_se_vazio em frete_db.py), então os testes checam contagem
relativa (antes/depois), não `len(...) == 1`. Usa o fixture
`banco_temporario` (conftest.py) — nunca toca no frete.db real.
"""

import sqlite3

import pytest

import frete_db as db


def test_inserir_e_listar_transporte(banco_temporario):
    antes = len(db.listar_transportes_admin())
    id_ = db.inserir_transporte("Fluvial", 1.80, 200, "balsa/barcaça")
    assert id_ is not None
    linhas = db.listar_transportes_admin()
    assert len(linhas) == antes + 1
    novo = next(r for r in linhas if r["id"] == id_)
    assert novo["nome"] == "Fluvial"
    assert novo["multiplicador"] == 1.80
    assert novo["fator_cubagem"] == 200
    assert novo["observacao"] == "balsa/barcaça"


def test_nome_duplicado_da_conflito(banco_temporario):
    db.inserir_transporte("Fluvial", 1.80, 200)
    with pytest.raises(sqlite3.IntegrityError):
        db.inserir_transporte("Fluvial", 2.00, 250)


def test_atualizar_transporte(banco_temporario):
    id_ = db.inserir_transporte("Fluvial", 1.80, 200)
    db.atualizar_transporte(id_, "Fluvial Regional", 1.90, 220, "reajuste")
    linha = next(r for r in db.listar_transportes_admin() if r["id"] == id_)
    assert linha["nome"] == "Fluvial Regional"
    assert linha["multiplicador"] == 1.90
    assert linha["fator_cubagem"] == 220
    assert linha["observacao"] == "reajuste"


def test_excluir_transporte(banco_temporario):
    antes = len(db.listar_transportes_admin())
    id_ = db.inserir_transporte("Fluvial", 1.80, 200)
    db.excluir_transporte(id_)
    linhas = db.listar_transportes_admin()
    assert len(linhas) == antes
    assert all(r["id"] != id_ for r in linhas)


def test_contar_transportes(banco_temporario):
    antes = db.contar_transportes()
    db.inserir_transporte("Fluvial", 1.80, 200)
    assert db.contar_transportes() == antes + 1
