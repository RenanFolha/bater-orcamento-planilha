# Desenvolvedor Chefe: RenanFolha

"""
Testes de aliquotas_icms (frete_db.py): matriz de ICMS por UF de origem ->
UF de destino, direcional, com UNIQUE(estado_origem, estado_destino)
case-insensitive na aplicação (mesmo padrão de prioridades_rota). Usa o
fixture `banco_temporario` (conftest.py) -- nunca toca no frete.db real.

Um banco novo já nasce com a matriz interestadual padrão semeada (ver
_seed_aliquotas_icms_interestadual), então os testes de CRUD isolado usam o
fixture `tabela_icms_vazia` (limpa a tabela depois do seed) pra não
esbarrar em conflito com uma UF/UF que já existe pré-cadastrada.
"""

import pytest

import db_conexao
import frete_db as db


@pytest.fixture
def tabela_icms_vazia(banco_temporario):
    with db.get_connection() as conn:
        conn.execute("DELETE FROM aliquotas_icms")
    return banco_temporario


def test_banco_novo_nasce_com_matriz_interestadual_semeada(banco_temporario):
    linhas = db.listar_aliquotas_icms_admin()
    assert len(linhas) == 27 * 2  # 1 linha "origem -> *" + 1 "origem -> própria UF" por UF
    por_par = {(r["estado_origem"], r["estado_destino"]): r["aliquota"] for r in linhas}
    assert por_par[("SP", "*")] == 7.0  # Sul/Sudeste (exceto ES) cobra 7% pra qualquer destino
    assert por_par[("BA", "*")] == 12.0  # demais UFs cobram 12% pra qualquer destino
    assert por_par[("SP", "SP")] == 18.0  # alíquota interna de SP (mais específica que "SP" -> "*")
    assert por_par[("RJ", "RJ")] == 19.0  # alíquota interna do RJ


def test_seed_nao_roda_de_novo_se_ja_tiver_linha(banco_temporario):
    # Simula alguém já tendo editado a matriz -- limpa tudo, cadastra só
    # uma linha customizada e recarrega o schema: o seed não deve
    # sobrescrever/completar o que já existe.
    with db.get_connection() as conn:
        conn.execute("DELETE FROM aliquotas_icms")
    db.inserir_aliquota_icms("SP", "RJ", 99.0, "customizada")
    db.init_db()
    linhas = db.listar_aliquotas_icms_admin()
    assert len(linhas) == 1
    assert linhas[0]["aliquota"] == 99.0


def test_inserir_e_listar_aliquota_icms(tabela_icms_vazia):
    id_ = db.inserir_aliquota_icms("SP", "RJ", 12.0, "interestadual padrão")
    assert id_ is not None
    linhas = db.listar_aliquotas_icms_admin()
    assert len(linhas) == 1
    assert linhas[0]["estado_origem"] == "SP"
    assert linhas[0]["estado_destino"] == "RJ"
    assert linhas[0]["aliquota"] == 12.0
    assert linhas[0]["observacao"] == "interestadual padrão"


def test_direcao_invertida_nao_conflita(tabela_icms_vazia):
    db.inserir_aliquota_icms("SP", "RJ", 12.0)
    id2 = db.inserir_aliquota_icms("RJ", "SP", 12.0)
    assert id2 is not None


def test_mesma_rota_da_conflito(tabela_icms_vazia):
    db.inserir_aliquota_icms("sp", "rj", 12.0)
    with pytest.raises(db_conexao.ConflitoIntegridade):
        db.inserir_aliquota_icms("SP", "RJ", 7.0)  # case-insensitive


def test_atualizar_aliquota_icms(tabela_icms_vazia):
    id_ = db.inserir_aliquota_icms("SP", "RJ", 12.0)
    db.atualizar_aliquota_icms(id_, "SP", "RJ", 7.0, "corrigida pra alíquota de produto importado")
    linha = db.listar_aliquotas_icms_admin()[0]
    assert linha["aliquota"] == 7.0
    assert linha["observacao"] == "corrigida pra alíquota de produto importado"


def test_excluir_aliquota_icms(tabela_icms_vazia):
    id_ = db.inserir_aliquota_icms("SP", "RJ", 12.0)
    db.excluir_aliquota_icms(id_)
    assert db.listar_aliquotas_icms_admin() == []


def test_curinga_aceito_como_uf(tabela_icms_vazia):
    id_ = db.inserir_aliquota_icms("*", "*", 18.0, "alíquota padrão de fallback")
    assert id_ is not None
    assert db.listar_aliquotas_icms_admin()[0]["estado_origem"] == "*"


def test_banco_novo_nasce_com_pis_cofins_semeado(banco_temporario):
    linha = db.obter_aliquota_pis_cofins()
    assert linha["aliquota"] == 9.25


def test_atualizar_aliquota_pis_cofins(banco_temporario):
    db.atualizar_aliquota_pis_cofins(3.65, "trocado pro regime cumulativo")
    linha = db.obter_aliquota_pis_cofins()
    assert linha["aliquota"] == 3.65
    assert linha["observacao"] == "trocado pro regime cumulativo"


def test_pis_cofins_seed_nao_roda_de_novo_se_ja_tiver_linha(banco_temporario):
    db.atualizar_aliquota_pis_cofins(3.65, "customizada")
    db.init_db()
    linha = db.obter_aliquota_pis_cofins()
    assert linha["aliquota"] == 3.65
