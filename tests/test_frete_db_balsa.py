# Desenvolvedor Chefe: RenanFolha

"""
Testes de taxas_balsa (frete_db.py): a taxa é direcional
(cidade_origem -> cidade_destino) e por veículo — duas linhas com a
mesma rota mas veículo diferente não conflitam, mas a mesma
rota+veículo duas vezes deve dar erro de conflito. Usa o fixture
`banco_temporario` (conftest.py) — nunca toca no frete.db real.
"""

import pytest

import db_conexao
import frete_db as db


def test_inserir_e_listar_taxa_balsa(banco_temporario):
    id_ = db.inserir_taxa_balsa("Belém", "Macapá", "VUC", "fixo", 120.0)
    assert id_ is not None
    linhas = db.listar_taxas_balsa_admin()
    assert len(linhas) == 1
    assert linhas[0]["cidade_origem"] == "Belém"
    assert linhas[0]["veiculo"] == "VUC"


def test_mesma_rota_veiculo_diferente_nao_conflita(banco_temporario):
    db.inserir_taxa_balsa("Belém", "Macapá", "VUC", "fixo", 120.0)
    id2 = db.inserir_taxa_balsa("Belém", "Macapá", "Carreta", "fixo", 350.0)
    assert id2 is not None
    assert len(db.listar_taxas_balsa_admin()) == 2


def test_direcao_invertida_nao_conflita(banco_temporario):
    # ida e volta são linhas independentes de propósito -- podem coexistir
    # com valores diferentes
    db.inserir_taxa_balsa("Belém", "Macapá", "VUC", "fixo", 120.0)
    id2 = db.inserir_taxa_balsa("Macapá", "Belém", "VUC", "fixo", 100.0)
    assert id2 is not None


def test_mesma_rota_e_veiculo_da_conflito(banco_temporario):
    # SQLite LOWER() só dobra maiúsculas ASCII (limitação pré-existente,
    # igual nas outras checagens de duplicidade do projeto) -- por isso o
    # teste varia só letras sem acento, não a acentuação em si.
    db.inserir_taxa_balsa("Belem", "Macapa", "VUC", "fixo", 120.0)
    with pytest.raises(db_conexao.ConflitoIntegridade):
        db.inserir_taxa_balsa("BELEM", "macapa", "vuc", "fixo", 130.0)  # case-insensitive


def test_atualizar_taxa_balsa(banco_temporario):
    id_ = db.inserir_taxa_balsa("Belém", "Macapá", "VUC", "fixo", 120.0)
    db.atualizar_taxa_balsa(id_, "Belém", "Macapá", "VUC", "fixo", 150.0, "reajuste")
    linha = db.listar_taxas_balsa_admin()[0]
    assert linha["valor"] == 150.0
    assert linha["observacao"] == "reajuste"


def test_excluir_taxa_balsa(banco_temporario):
    id_ = db.inserir_taxa_balsa("Belém", "Macapá", "VUC", "fixo", 120.0)
    db.excluir_taxa_balsa(id_)
    assert db.listar_taxas_balsa_admin() == []
