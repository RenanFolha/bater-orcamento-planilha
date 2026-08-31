"""
Testes de categorias (frete_db.py): `nome` é UNIQUE (case-sensitive).
`init_db()` já popula o banco com categorias de exemplo (ver
_seed_se_vazio em frete_db.py), então os testes checam contagem
relativa (antes/depois), não `len(...) == 1`. Usa o fixture
`banco_temporario` (conftest.py) — nunca toca no frete.db real.
"""

import sqlite3

import pytest

import frete_db as db


def test_inserir_e_listar_categoria(banco_temporario):
    antes = len(db.listar_categorias_admin())
    id_ = db.inserir_categoria("Cosméticos", 1.15, "sensível a temperatura")
    assert id_ is not None
    linhas = db.listar_categorias_admin()
    assert len(linhas) == antes + 1
    nova = next(r for r in linhas if r["id"] == id_)
    assert nova["nome"] == "Cosméticos"
    assert nova["multiplicador"] == 1.15
    assert nova["observacao"] == "sensível a temperatura"


def test_nome_duplicado_da_conflito(banco_temporario):
    db.inserir_categoria("Cosméticos", 1.15)
    with pytest.raises(sqlite3.IntegrityError):
        db.inserir_categoria("Cosméticos", 1.25)


def test_atualizar_categoria(banco_temporario):
    id_ = db.inserir_categoria("Cosméticos", 1.15)
    db.atualizar_categoria(id_, "Cosméticos Premium", 1.30, "reajuste")
    linha = next(r for r in db.listar_categorias_admin() if r["id"] == id_)
    assert linha["nome"] == "Cosméticos Premium"
    assert linha["multiplicador"] == 1.30
    assert linha["observacao"] == "reajuste"


def test_excluir_categoria(banco_temporario):
    antes = len(db.listar_categorias_admin())
    id_ = db.inserir_categoria("Cosméticos", 1.15)
    db.excluir_categoria(id_)
    linhas = db.listar_categorias_admin()
    assert len(linhas) == antes
    assert all(r["id"] != id_ for r in linhas)


def test_contar_categorias(banco_temporario):
    antes = db.contar_categorias()
    db.inserir_categoria("Cosméticos", 1.15)
    assert db.contar_categorias() == antes + 1
