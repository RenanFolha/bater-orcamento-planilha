# Desenvolvedor Chefe: RenanFolha

"""
Testes de orcamentos_historico (frete_db.py) que ainda não tinham
cobertura no nível de banco (o resto do CRUD já é exercitado via API,
ver tests/test_main_api.py). Usa o fixture `banco_temporario`
(conftest.py) — nunca toca no frete.db real.
"""

import frete_db as db


def test_proximo_codigo_orcamento_incrementa_a_partir_do_ultimo(banco_temporario):
    db.salvar_orcamento_historico(
        cliente="Cliente A", responsavel="Fulano", origem_resumo="", destino_resumo="",
        veiculo="", distancia_km=0, valor_mercadoria=0, frete_total=0, dados_json="{}",
    )
    codigo2 = db.salvar_orcamento_historico(
        cliente="Cliente B", responsavel="Fulano", origem_resumo="", destino_resumo="",
        veiculo="", distancia_km=0, valor_mercadoria=0, frete_total=0, dados_json="{}",
    )
    assert codigo2["codigo"] == "ORC-0002"


def test_proximo_codigo_orcamento_cai_pro_1_quando_ultimo_codigo_malformado(banco_temporario):
    # Defensivo: se por algum motivo o último registro tiver um código
    # fora do formato ORC-NNNN (ex: importado de outro sistema, editado
    # manualmente no DB Browser), não pode travar a geração do próximo --
    # cai pra 1 em vez de propagar ValueError/IndexError.
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO orcamentos_historico "
            "(codigo, criado_em, cliente, responsavel, origem_resumo, destino_resumo, veiculo, "
            "distancia_km, valor_mercadoria, frete_total, status, dados_json, criado_por) "
            "VALUES ('codigo-sem-numero', '2026-01-01T00:00:00', 'X', 'Y', '', '', '', 0, 0, 0, "
            "'Fechado', '{}', '')"
        )
        codigo = db._proximo_codigo_orcamento(conn)
    assert codigo == "ORC-0001"
