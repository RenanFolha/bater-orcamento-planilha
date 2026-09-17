# Desenvolvedor Chefe: RenanFolha

"""
Testes de distancias_fixas (frete_db.py): sobrepõe o cálculo automático
de distância pra um corredor cidade_origem -> cidade_destino, direcional
e com curinga "*" (mesmo mecanismo de taxas_balsa). Usa o fixture
`banco_temporario` (conftest.py) — nunca toca no frete.db real.
"""

import pytest

import db_conexao
import frete_db as db


def test_inserir_e_listar_distancia_fixa(banco_temporario):
    id_ = db.inserir_distancia_fixa("Belem", "Manaus", 2096)
    assert id_ is not None
    linhas = db.listar_distancias_fixas_admin()
    assert len(linhas) == 1
    assert linhas[0]["cidade_origem"] == "Belem"
    assert linhas[0]["distancia_km"] == 2096


def test_direcao_invertida_nao_conflita(banco_temporario):
    db.inserir_distancia_fixa("Belem", "Manaus", 2096)
    id2 = db.inserir_distancia_fixa("Manaus", "Belem", 2096)
    assert id2 is not None


def test_mesmo_corredor_da_conflito(banco_temporario):
    db.inserir_distancia_fixa("Belem", "Manaus", 2096)
    with pytest.raises(db_conexao.ConflitoIntegridade):
        db.inserir_distancia_fixa("BELEM", "manaus", 2200)


def test_atualizar_distancia_fixa(banco_temporario):
    id_ = db.inserir_distancia_fixa("Belem", "Manaus", 2096)
    db.atualizar_distancia_fixa(id_, "Belem", "Manaus", 2100, "ajustada")
    linha = db.listar_distancias_fixas_admin()[0]
    assert linha["distancia_km"] == 2100
    assert linha["observacao"] == "ajustada"


def test_atualizar_distancia_fixa_com_corredor_de_outra_linha_da_conflito(banco_temporario):
    db.inserir_distancia_fixa("Belem", "Manaus", 2096)
    id2 = db.inserir_distancia_fixa("Belem", "Santarem", 700)
    with pytest.raises(db_conexao.ConflitoIntegridade):
        db.atualizar_distancia_fixa(id2, "Belem", "Manaus", 2100)


def test_excluir_distancia_fixa(banco_temporario):
    id_ = db.inserir_distancia_fixa("Belem", "Manaus", 2096)
    db.excluir_distancia_fixa(id_)
    assert db.listar_distancias_fixas_admin() == []
