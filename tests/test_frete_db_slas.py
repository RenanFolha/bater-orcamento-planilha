# Desenvolvedor Chefe: RenanFolha

"""
Testes de slas (frete_db.py): `nome` é UNIQUE (case-sensitive).
`init_db()` já popula o banco com SLAs de exemplo (ver
_seed_se_vazio em frete_db.py), então os testes checam contagem
relativa (antes/depois), não `len(...) == 1`. Usa o fixture
`banco_temporario` (conftest.py) — nunca toca no frete.db real.
"""

import sqlite3

import pytest

import frete_db as db


def test_inserir_e_listar_sla(banco_temporario):
    antes = len(db.listar_slas_admin())
    id_ = db.inserir_sla("Mesmo dia", 3.00, 0, "entrega no mesmo dia útil")
    assert id_ is not None
    linhas = db.listar_slas_admin()
    assert len(linhas) == antes + 1
    novo = next(r for r in linhas if r["id"] == id_)
    assert novo["nome"] == "Mesmo dia"
    assert novo["multiplicador"] == 3.00
    assert novo["prazo_dias"] == 0
    assert novo["observacao"] == "entrega no mesmo dia útil"


def test_nome_duplicado_da_conflito(banco_temporario):
    db.inserir_sla("Mesmo dia", 3.00, 0)
    with pytest.raises(sqlite3.IntegrityError):
        db.inserir_sla("Mesmo dia", 3.50, 0)


def test_atualizar_sla(banco_temporario):
    id_ = db.inserir_sla("Mesmo dia", 3.00, 0)
    db.atualizar_sla(id_, "Mesmo dia útil", 3.20, 1, "reajuste")
    linha = next(r for r in db.listar_slas_admin() if r["id"] == id_)
    assert linha["nome"] == "Mesmo dia útil"
    assert linha["multiplicador"] == 3.20
    assert linha["prazo_dias"] == 1
    assert linha["observacao"] == "reajuste"


def test_excluir_sla(banco_temporario):
    antes = len(db.listar_slas_admin())
    id_ = db.inserir_sla("Mesmo dia", 3.00, 0)
    db.excluir_sla(id_)
    linhas = db.listar_slas_admin()
    assert len(linhas) == antes
    assert all(r["id"] != id_ for r in linhas)


def test_contar_slas(banco_temporario):
    antes = db.contar_slas()
    db.inserir_sla("Mesmo dia", 3.00, 0)
    assert db.contar_slas() == antes + 1
