# Desenvolvedor Chefe: RenanFolha

"""
Testes de filiais (frete_db.py): `nome` é UNIQUE (sem COLLATE NOCASE —
duplicidade só é bloqueada com o nome idêntico, não case-insensitive) e
`atualizar_filial` sempre limpa latitude/longitude em cache, porque o
endereço pode ter mudado — força uma nova geocodificação na próxima vez
que a filial for usada num cálculo. Usa o fixture `banco_temporario`
(conftest.py) — nunca toca no frete.db real.

`init_db()` já popula o banco com filiais de exemplo (ver
_seed_se_vazio em frete_db.py), então os testes checam contagem
relativa (antes/depois), não `len(...) == 1`.
"""

import sqlite3

import pytest

import frete_db as db


def test_inserir_e_listar_filial(banco_temporario):
    antes = len(db.listar_filiais_admin())
    id_ = db.inserir_filial("Recife", "Rua Nova, 100, Recife, PE")
    assert id_ is not None
    linhas = db.listar_filiais_admin()
    assert len(linhas) == antes + 1
    nova = next(r for r in linhas if r["id"] == id_)
    assert nova["nome"] == "Recife"
    assert nova["endereco"] == "Rua Nova, 100, Recife, PE"
    assert nova["latitude"] is None
    assert nova["longitude"] is None


def test_nome_duplicado_da_conflito(banco_temporario):
    db.inserir_filial("Recife", "Rua Nova, 100, Recife, PE")
    with pytest.raises(sqlite3.IntegrityError):
        db.inserir_filial("Recife", "Outro endereço qualquer")


def test_atualizar_filial(banco_temporario):
    id_ = db.inserir_filial("Recife", "Rua Nova, 100, Recife, PE")
    db.atualizar_filial(id_, "Recife - Centro", "Av. Nova, 200, Recife, PE")
    linha = next(r for r in db.listar_filiais_admin() if r["id"] == id_)
    assert linha["nome"] == "Recife - Centro"
    assert linha["endereco"] == "Av. Nova, 200, Recife, PE"


def test_atualizar_filial_limpa_coordenadas_em_cache(banco_temporario):
    id_ = db.inserir_filial("Recife", "Rua Nova, 100, Recife, PE")
    db.atualizar_coordenadas_filial("Recife", -8.05, -34.9)
    linha = next(r for r in db.listar_filiais_admin() if r["id"] == id_)
    assert linha["latitude"] == -8.05

    # edita o endereço -- as coordenadas em cache não valem mais
    db.atualizar_filial(id_, "Recife", "Rua Outra, 999, Recife, PE")
    linha = next(r for r in db.listar_filiais_admin() if r["id"] == id_)
    assert linha["latitude"] is None
    assert linha["longitude"] is None


def test_excluir_filial(banco_temporario):
    antes = len(db.listar_filiais_admin())
    id_ = db.inserir_filial("Recife", "Rua Nova, 100, Recife, PE")
    db.excluir_filial(id_)
    linhas = db.listar_filiais_admin()
    assert len(linhas) == antes
    assert all(r["id"] != id_ for r in linhas)


def test_contar_filiais(banco_temporario):
    antes = db.contar_filiais()
    db.inserir_filial("Recife", "Rua Nova, 100, Recife, PE")
    assert db.contar_filiais() == antes + 1
