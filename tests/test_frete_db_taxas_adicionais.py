# Desenvolvedor Chefe: RenanFolha

"""
Testes de taxas_adicionais (frete_db.py): `nome` é UNIQUE
(case-sensitive) e `tipo` tem CHECK ('fixo' ou 'percentual').
`init_db()` já popula o banco com taxas de exemplo (GRIS, Ad Valorem
etc. — ver _seed_se_vazio em frete_db.py), então os testes checam
contagem relativa (antes/depois), não `len(...) == 1`. Usa o fixture
`banco_temporario` (conftest.py) — nunca toca no frete.db real.
"""

import sqlite3

import pytest

import frete_db as db


def test_inserir_e_listar_taxa_adicional(banco_temporario):
    antes = len(db.listar_taxas_adicionais_admin())
    id_ = db.inserir_taxa_adicional("Seguro Extra", "percentual", 0.40, "cobertura adicional")
    assert id_ is not None
    linhas = db.listar_taxas_adicionais_admin()
    assert len(linhas) == antes + 1
    nova = next(r for r in linhas if r["id"] == id_)
    assert nova["nome"] == "Seguro Extra"
    assert nova["tipo"] == "percentual"
    assert nova["valor"] == 0.40
    assert nova["observacao"] == "cobertura adicional"


def test_nome_duplicado_da_conflito(banco_temporario):
    db.inserir_taxa_adicional("Seguro Extra", "percentual", 0.40)
    with pytest.raises(sqlite3.IntegrityError):
        db.inserir_taxa_adicional("Seguro Extra", "fixo", 20.00)


def test_tipo_invalido_da_erro(banco_temporario):
    with pytest.raises(sqlite3.IntegrityError):
        db.inserir_taxa_adicional("Seguro Extra", "porcentagem", 0.40)


def test_atualizar_taxa_adicional(banco_temporario):
    id_ = db.inserir_taxa_adicional("Seguro Extra", "percentual", 0.40)
    db.atualizar_taxa_adicional(id_, "Seguro Extra", "fixo", 20.00, "trocou pra fixo")
    linha = next(r for r in db.listar_taxas_adicionais_admin() if r["id"] == id_)
    assert linha["tipo"] == "fixo"
    assert linha["valor"] == 20.00
    assert linha["observacao"] == "trocou pra fixo"


def test_excluir_taxa_adicional(banco_temporario):
    antes = len(db.listar_taxas_adicionais_admin())
    id_ = db.inserir_taxa_adicional("Seguro Extra", "percentual", 0.40)
    db.excluir_taxa_adicional(id_)
    linhas = db.listar_taxas_adicionais_admin()
    assert len(linhas) == antes
    assert all(r["id"] != id_ for r in linhas)
