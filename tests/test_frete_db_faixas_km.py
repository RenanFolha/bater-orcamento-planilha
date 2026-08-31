# Desenvolvedor Chefe: RenanFolha

"""
Testes de faixas_km_veiculo (frete_db.py): CRUD básico da tabela usada
pra escalonar o R$/km por distância, por veículo. Usa o fixture
`banco_temporario` (conftest.py) — nunca toca no frete.db real.
"""

import frete_db as db


def test_inserir_e_listar_faixa_km_veiculo(banco_temporario):
    id_ = db.inserir_faixa_km_veiculo("Carreta", 0, 600, 5.72)
    assert id_ is not None
    linhas = db.listar_faixas_km_veiculo_admin()
    assert len(linhas) == 1
    assert linhas[0]["veiculo"] == "Carreta"
    assert linhas[0]["tarifa_km"] == 5.72


def test_varias_faixas_para_o_mesmo_veiculo(banco_temporario):
    db.inserir_faixa_km_veiculo("Carreta", 0, 600, 5.72)
    db.inserir_faixa_km_veiculo("Carreta", 601, 700, 5.25)
    db.inserir_faixa_km_veiculo("Carreta", 701, 800, 5.00)
    db.inserir_faixa_km_veiculo("Carreta", 801, 999999, 4.80)
    assert len(db.listar_faixas_km_veiculo_admin()) == 4


def test_atualizar_faixa_km_veiculo(banco_temporario):
    id_ = db.inserir_faixa_km_veiculo("Carreta", 0, 600, 5.72)
    db.atualizar_faixa_km_veiculo(id_, "Carreta", 0, 600, 6.00, "reajuste")
    linha = db.listar_faixas_km_veiculo_admin()[0]
    assert linha["tarifa_km"] == 6.00
    assert linha["observacao"] == "reajuste"


def test_excluir_faixa_km_veiculo(banco_temporario):
    id_ = db.inserir_faixa_km_veiculo("Carreta", 0, 600, 5.72)
    db.excluir_faixa_km_veiculo(id_)
    assert db.listar_faixas_km_veiculo_admin() == []
