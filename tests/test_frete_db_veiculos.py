# Desenvolvedor Chefe: RenanFolha

"""
Testes de veiculos (frete_db.py): `nome` é UNIQUE (case-sensitive).
`init_db()` já popula o banco com veículos de exemplo (ver
_seed_se_vazio em frete_db.py), então os testes checam contagem
relativa (antes/depois), não `len(...) == 1`. Usa o fixture
`banco_temporario` (conftest.py) — nunca toca no frete.db real.
"""

import pytest

import db_conexao
import frete_db as db


def test_inserir_e_listar_veiculo(banco_temporario):
    antes = len(db.listar_veiculos_admin())
    id_ = db.inserir_veiculo(
        "Bitrem", 20000, 40000, 6.20, 0.30,
        tarifa_km_retorno=1.5, tarifa_km_manutencao=0.8, capacidade_m3=120.0,
        percentual_capacidade_util=85, observacao="teste",
    )
    assert id_ is not None
    linhas = db.listar_veiculos_admin()
    assert len(linhas) == antes + 1
    novo = next(r for r in linhas if r["id"] == id_)
    assert novo["nome"] == "Bitrem"
    assert novo["de"] == 20000
    assert novo["ate"] == 40000
    assert novo["tarifa_km"] == 6.20
    assert novo["valor_tonelada_excedente"] == 0.30
    assert novo["tarifa_km_retorno"] == 1.5
    assert novo["tarifa_km_manutencao"] == 0.8
    assert novo["capacidade_m3"] == 120.0
    assert novo["percentual_capacidade_util"] == 85
    assert novo["observacao"] == "teste"


def test_inserir_veiculo_usa_defaults(banco_temporario):
    id_ = db.inserir_veiculo("Bitrem", 20000, 40000, 6.20, 0.30)
    novo = next(r for r in db.listar_veiculos_admin() if r["id"] == id_)
    assert novo["tarifa_km_retorno"] == 0
    assert novo["tarifa_km_manutencao"] == 0
    assert novo["capacidade_m3"] == 0
    assert novo["percentual_capacidade_util"] == 80


def test_nome_duplicado_da_conflito(banco_temporario):
    db.inserir_veiculo("Bitrem", 20000, 40000, 6.20, 0.30)
    with pytest.raises(db_conexao.ConflitoIntegridade):
        db.inserir_veiculo("Bitrem", 10000, 30000, 5.00, 0.20)


def test_atualizar_veiculo(banco_temporario):
    id_ = db.inserir_veiculo("Bitrem", 20000, 40000, 6.20, 0.30)
    db.atualizar_veiculo(
        id_, "Bitrem XL", 20000, 45000, 6.50, 0.35,
        tarifa_km_retorno=2.0, tarifa_km_manutencao=1.0, capacidade_m3=130.0,
        percentual_capacidade_util=90, observacao="ajustado",
    )
    linha = next(r for r in db.listar_veiculos_admin() if r["id"] == id_)
    assert linha["nome"] == "Bitrem XL"
    assert linha["ate"] == 45000
    assert linha["tarifa_km"] == 6.50
    assert linha["observacao"] == "ajustado"


def test_excluir_veiculo(banco_temporario):
    antes = len(db.listar_veiculos_admin())
    id_ = db.inserir_veiculo("Bitrem", 20000, 40000, 6.20, 0.30)
    db.excluir_veiculo(id_)
    linhas = db.listar_veiculos_admin()
    assert len(linhas) == antes
    assert all(r["id"] != id_ for r in linhas)


def test_contar_veiculos(banco_temporario):
    antes = db.contar_veiculos()
    db.inserir_veiculo("Bitrem", 20000, 40000, 6.20, 0.30)
    assert db.contar_veiculos() == antes + 1
