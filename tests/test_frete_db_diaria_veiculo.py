# Desenvolvedor Chefe: RenanFolha

"""
Testes de taxas_diaria_veiculo (frete_db.py): diária de carreta + cavalo
por UF, sem curinga, com UNIQUE(uf) case-insensitive na aplicação (mesmo
padrão de aliquotas_icms/prioridades_rota). Usa o fixture
`banco_temporario` (conftest.py) -- nunca toca no frete.db real.

Um banco novo já nasce com a diária do AM pré-semeada (ver
_seed_se_vazio), então os testes de CRUD isolado usam o fixture
`tabela_diaria_vazia` (limpa a tabela depois do seed) pra não esbarrar em
conflito com a UF já pré-cadastrada.
"""

import pytest

import db_conexao
import frete_db as db


@pytest.fixture
def tabela_diaria_vazia(banco_temporario):
    with db.get_connection() as conn:
        conn.execute("DELETE FROM taxas_diaria_veiculo")
    return banco_temporario


def test_banco_novo_nasce_com_diaria_am_semeada(banco_temporario):
    linhas = db.listar_taxas_diaria_veiculo_admin()
    assert len(linhas) == 1
    assert linhas[0]["uf"] == "AM"
    assert linhas[0]["valor_carreta"] == 220.0
    assert linhas[0]["valor_cavalo"] == 819.0


def test_diaria_seed_nao_roda_de_novo_se_ja_tiver_linha(banco_temporario):
    with db.get_connection() as conn:
        conn.execute("DELETE FROM taxas_diaria_veiculo")
    db.inserir_taxa_diaria_veiculo("PA", 100.0, 300.0, "customizada")
    db.init_db()
    linhas = db.listar_taxas_diaria_veiculo_admin()
    assert len(linhas) == 1
    assert linhas[0]["uf"] == "PA"


def test_inserir_e_listar_taxa_diaria_veiculo(tabela_diaria_vazia):
    id_ = db.inserir_taxa_diaria_veiculo("rr", 150.0, 500.0, "teste")
    assert id_ is not None
    linhas = db.listar_taxas_diaria_veiculo_admin()
    assert len(linhas) == 1
    # UF sempre salva maiúscula, mesmo digitada em minúsculo.
    assert linhas[0]["uf"] == "RR"
    assert linhas[0]["valor_carreta"] == 150.0
    assert linhas[0]["valor_cavalo"] == 500.0
    assert linhas[0]["observacao"] == "teste"


def test_uf_duplicada_da_conflito(tabela_diaria_vazia):
    db.inserir_taxa_diaria_veiculo("am", 220.0, 819.0)
    with pytest.raises(db_conexao.ConflitoIntegridade):
        db.inserir_taxa_diaria_veiculo("AM", 999.0, 999.0)  # case-insensitive


def test_atualizar_taxa_diaria_veiculo(tabela_diaria_vazia):
    id_ = db.inserir_taxa_diaria_veiculo("AM", 220.0, 819.0)
    db.atualizar_taxa_diaria_veiculo(id_, "AM", 250.0, 900.0, "reajustado")
    linha = db.listar_taxas_diaria_veiculo_admin()[0]
    assert linha["valor_carreta"] == 250.0
    assert linha["valor_cavalo"] == 900.0
    assert linha["observacao"] == "reajustado"


def test_atualizar_com_uf_de_outra_linha_da_conflito(tabela_diaria_vazia):
    db.inserir_taxa_diaria_veiculo("AM", 220.0, 819.0)
    id2 = db.inserir_taxa_diaria_veiculo("PA", 100.0, 300.0)
    with pytest.raises(db_conexao.ConflitoIntegridade):
        db.atualizar_taxa_diaria_veiculo(id2, "AM", 100.0, 300.0)


def test_excluir_taxa_diaria_veiculo(tabela_diaria_vazia):
    id_ = db.inserir_taxa_diaria_veiculo("AM", 220.0, 819.0)
    db.excluir_taxa_diaria_veiculo(id_)
    assert db.listar_taxas_diaria_veiculo_admin() == []
