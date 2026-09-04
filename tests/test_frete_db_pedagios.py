# Desenvolvedor Chefe: RenanFolha

"""
Testes do catálogo de praças de pedágio e dos corredores que as ligam
(frete_db.py): pracas_pedagio é o catálogo (preço por número de eixos,
único por (nome, rodovia)); pedagios_rota liga um corredor direcional
cidade_origem -> cidade_destino a uma ou mais praças (único por
(cidade_origem, cidade_destino, praca_id)). Usa o fixture
`banco_temporario` (conftest.py) — nunca toca no frete.db real.
"""

import pytest

import db_conexao
import frete_db as db


def test_inserir_e_listar_praca_pedagio(banco_temporario):
    id_ = db.inserir_praca_pedagio(
        "Praça 5", "BR-101", "ViaSul", uf="SC", km="123",
        valor_eixo_2=12.4, valor_eixo_3=18.6,
    )
    assert id_ is not None
    linhas = db.listar_pracas_pedagio_admin()
    assert len(linhas) == 1
    assert linhas[0]["nome"] == "Praça 5"
    assert linhas[0]["valor_eixo_2"] == 12.4
    assert linhas[0]["valor_eixo_9"] == 0


def test_mesmo_nome_rodovia_diferente_nao_conflita(banco_temporario):
    db.inserir_praca_pedagio("Praça Central", "BR-101", "ViaSul")
    id2 = db.inserir_praca_pedagio("Praça Central", "BR-116", "Arteris")
    assert id2 is not None
    assert len(db.listar_pracas_pedagio_admin()) == 2


def test_mesmo_nome_e_rodovia_da_conflito(banco_temporario):
    # SQLite LOWER() só dobra maiúsculas ASCII (limitação pré-existente,
    # igual nas outras checagens de duplicidade do projeto) -- por isso o
    # teste varia só letras sem acento, não a acentuação em si.
    db.inserir_praca_pedagio("Praca Central", "BR-101", "ViaSul")
    with pytest.raises(db_conexao.ConflitoIntegridade):
        db.inserir_praca_pedagio("PRACA CENTRAL", "br-101", "Outra")


def test_atualizar_praca_pedagio(banco_temporario):
    id_ = db.inserir_praca_pedagio("Praça 5", "BR-101", "ViaSul", valor_eixo_2=10)
    db.atualizar_praca_pedagio(id_, "Praça 5", "BR-101", "ViaSul", valor_eixo_2=15, observacao="reajuste")
    linha = db.listar_pracas_pedagio_admin()[0]
    assert linha["valor_eixo_2"] == 15
    assert linha["observacao"] == "reajuste"


def test_excluir_praca_pedagio(banco_temporario):
    id_ = db.inserir_praca_pedagio("Praça 5", "BR-101", "ViaSul")
    db.excluir_praca_pedagio(id_)
    assert db.listar_pracas_pedagio_admin() == []


def test_inserir_e_listar_pedagio_rota(banco_temporario):
    praca_id = db.inserir_praca_pedagio("Praça 5", "BR-101", "ViaSul", valor_eixo_2=12.4)
    id_ = db.inserir_pedagio_rota("Curitiba", "Florianópolis", praca_id)
    assert id_ is not None
    linhas = db.listar_pedagios_rota_admin()
    assert len(linhas) == 1
    assert linhas[0]["praca_nome"] == "Praça 5"
    assert linhas[0]["praca_rodovia"] == "BR-101"


def test_mesmo_corredor_praca_diferente_nao_conflita(banco_temporario):
    p1 = db.inserir_praca_pedagio("Praça 5", "BR-101", "ViaSul")
    p2 = db.inserir_praca_pedagio("Praça 8", "BR-101", "ViaSul")
    db.inserir_pedagio_rota("Curitiba", "Florianópolis", p1)
    id2 = db.inserir_pedagio_rota("Curitiba", "Florianópolis", p2)
    assert id2 is not None
    assert len(db.listar_pedagios_rota_admin()) == 2


def test_mesmo_corredor_e_praca_da_conflito(banco_temporario):
    # mesma limitação de LOWER() do teste acima -- varia só letras ASCII
    praca_id = db.inserir_praca_pedagio("Praca 5", "BR-101", "ViaSul")
    db.inserir_pedagio_rota("Curitiba", "Florianopolis", praca_id)
    with pytest.raises(db_conexao.ConflitoIntegridade):
        db.inserir_pedagio_rota("CURITIBA", "florianopolis", praca_id)


def test_excluir_praca_em_uso_falha_por_fk(banco_temporario):
    praca_id = db.inserir_praca_pedagio("Praça 5", "BR-101", "ViaSul")
    db.inserir_pedagio_rota("Curitiba", "Florianópolis", praca_id)
    with pytest.raises(db_conexao.ConflitoIntegridade):
        db.excluir_praca_pedagio(praca_id)


def test_excluir_pedagio_rota(banco_temporario):
    praca_id = db.inserir_praca_pedagio("Praça 5", "BR-101", "ViaSul")
    id_ = db.inserir_pedagio_rota("Curitiba", "Florianópolis", praca_id)
    db.excluir_pedagio_rota(id_)
    assert db.listar_pedagios_rota_admin() == []


def test_importar_csv_cria_e_atualiza(banco_temporario):
    csv1 = (
        "nome,rodovia,concessionaria,uf,km,valor_eixo_2,valor_eixo_3\n"
        "Praça 5,BR-101,ViaSul,SC,123,12.4,18.6\n"
        "Praça 8,BR-101,ViaSul,SC,180,10.0,15.0\n"
    )
    resultado = db.importar_pracas_pedagio_csv(csv1)
    assert resultado["criadas"] == 2
    assert resultado["atualizadas"] == 0
    assert resultado["erros"] == []
    assert len(db.listar_pracas_pedagio_admin()) == 2

    csv2 = (
        "nome,rodovia,concessionaria,valor_eixo_2\n"
        "Praça 5,BR-101,ViaSul,20.0\n"  # já existe -> atualiza
        "Praça 9,BR-101,ViaSul,8.0\n"  # nova -> cria
    )
    resultado2 = db.importar_pracas_pedagio_csv(csv2)
    assert resultado2["criadas"] == 1
    assert resultado2["atualizadas"] == 1
    assert len(db.listar_pracas_pedagio_admin()) == 3
    praca5 = next(p for p in db.listar_pracas_pedagio_admin() if p["nome"] == "Praça 5")
    assert praca5["valor_eixo_2"] == 20.0


def test_importar_csv_linha_sem_campo_obrigatorio_vira_erro(banco_temporario):
    csv = "nome,rodovia,concessionaria\nPraça 5,BR-101,\n"
    resultado = db.importar_pracas_pedagio_csv(csv)
    assert resultado["criadas"] == 0
    assert len(resultado["erros"]) == 1
    assert "linha 2" in resultado["erros"][0]


def test_importar_csv_valor_invalido_vira_erro(banco_temporario):
    csv = "nome,rodovia,concessionaria,valor_eixo_2\nPraça 5,BR-101,ViaSul,abc\n"
    resultado = db.importar_pracas_pedagio_csv(csv)
    assert resultado["criadas"] == 0
    assert len(resultado["erros"]) == 1
