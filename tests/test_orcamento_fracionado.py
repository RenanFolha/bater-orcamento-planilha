# Desenvolvedor Chefe: RenanFolha

"""Testes de integração do orçamento Fracionado (POST /orcamento/fracionado)
e do CRUD administrativo das faixas de peso/distância que alimentam o
frete base dele (ver frete_service.calcular_orcamento_fracionado)."""

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def client(banco_temporario):
    with TestClient(main.app) as c:
        yield c


def _login(client, username="admin", senha="admin123"):
    r = client.post("/auth/login", json={"username": username, "senha": senha})
    assert r.status_code == 200, r.text
    return r


def _payload(**overrides):
    payload = dict(
        peso=80,
        paletes=[{"comprimento": 100, "largura": 100, "altura": 100}],
        distancia=350,
        valor_mercadoria=1200,
        categoria="Geral",
        transporte="Rodoviário",
        sla="Padrão",
        veiculo="Caminhonete",
    )
    payload.update(overrides)
    return payload


def test_orcamento_fracionado_e_publico_sem_login(client):
    r = client.post("/orcamento/fracionado", json=_payload())
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["resultado"]["frete_total"] > 0
    assert data["entrada"]["tipo_frete"] == "Fracionado"
    assert data["entrada"]["veiculo"] == "Caminhonete"


def test_orcamento_fracionado_usa_faixa_de_peso_e_distancia_nao_veiculo(client):
    r = client.post("/orcamento/fracionado", json=_payload())
    assert r.status_code == 200, r.text
    calc = r.json()["calculos_intermediarios"]
    # Frete base é a soma do custo por faixa de peso + faixa de distância —
    # não tem custo_km nem custo_peso_excedente (conceitos do Carreta
    # Fechada, ver frete_service.calcular_orcamento).
    assert calc["custo_base_peso"] > 0
    assert calc["custo_base_distancia"] > 0
    assert calc["frete_base"] == round(calc["custo_base_peso"] + calc["custo_base_distancia"], 2)
    assert "custo_km" not in calc
    assert "custo_manutencao" not in calc
    assert "custo_retorno" not in calc


def test_orcamento_fracionado_veiculo_invalido_da_422(client):
    r = client.post("/orcamento/fracionado", json=_payload(veiculo="Nave Espacial"))
    assert r.status_code == 422


def test_orcamento_fracionado_margem_30_recusada_sem_login(client):
    r = client.post("/orcamento/fracionado", json=_payload(margem_lucro_pct=30))
    assert r.status_code == 403


def test_orcamento_fracionado_margem_30_permitida_pra_admin(client):
    _login(client)
    r = client.post("/orcamento/fracionado", json=_payload(margem_lucro_pct=30))
    assert r.status_code == 200, r.text


def test_admin_faixas_peso_fracionado_exige_login(client):
    assert client.get("/admin/faixas-peso-fracionado").status_code == 401


def test_admin_faixas_peso_fracionado_crud(client):
    _login(client)

    # Banco novo já nasce com as faixas de exemplo do seed (tipo_frete
    # "Fracionado") -- todas as linhas devolvidas aqui são desse tipo,
    # mesmo a tabela guardando também linhas legadas de "Carreta Fechada".
    r = client.get("/admin/faixas-peso-fracionado")
    assert r.status_code == 200
    faixas_iniciais = r.json()
    assert len(faixas_iniciais) > 0
    assert all(f["tipo_frete"] == "Fracionado" for f in faixas_iniciais)

    r = client.post("/admin/faixas-peso-fracionado", json={
        "de": 100000, "ate": 200000, "tarifa_base": 999.0, "custo_kg_adicional": 2.0, "observacao": "teste",
    })
    assert r.status_code == 200, r.text
    novo_id = r.json()["id"]

    r = client.put(f"/admin/faixas-peso-fracionado/{novo_id}", json={
        "de": 100000, "ate": 200000, "tarifa_base": 1000.0, "custo_kg_adicional": 2.5, "observacao": "teste editado",
    })
    assert r.status_code == 200, r.text

    r = client.get("/admin/faixas-peso-fracionado")
    linha = next(f for f in r.json() if f["id"] == novo_id)
    assert linha["tarifa_base"] == 1000.0
    assert linha["tipo_frete"] == "Fracionado"

    r = client.delete(f"/admin/faixas-peso-fracionado/{novo_id}")
    assert r.status_code == 200, r.text


def test_admin_faixas_distancia_fracionado_crud(client):
    _login(client)

    r = client.get("/admin/faixas-distancia-fracionado")
    assert r.status_code == 200
    assert all(f["tipo_frete"] == "Fracionado" for f in r.json())

    r = client.post("/admin/faixas-distancia-fracionado", json={
        "de": 5000, "ate": 999999, "taxa_fixa": 500.0, "tarifa_km": 1.0, "observacao": "teste",
    })
    assert r.status_code == 200, r.text
    novo_id = r.json()["id"]

    r = client.delete(f"/admin/faixas-distancia-fracionado/{novo_id}")
    assert r.status_code == 200, r.text


def test_orcamento_fracionado_pode_ser_salvo_no_historico(client):
    _login(client)
    r = client.post("/orcamento/fracionado", json=_payload())
    resultado = r.json()

    r = client.post("/historico", json={
        "cliente": "Cliente Teste", "responsavel": "Fulano",
        "origem_resumo": "Filial A", "destino_resumo": "Filial B",
        "veiculo": resultado["entrada"]["veiculo"],
        "distancia_km": resultado["entrada"]["distancia_km"],
        "valor_mercadoria": resultado["entrada"]["valor_mercadoria"],
        "frete_total": resultado["resultado"]["frete_total"],
        "dados": {"payload": _payload(), "resultado": resultado},
    })
    assert r.status_code == 200, r.text
    codigo = r.json()["codigo"]

    r = client.get(f"/historico/{codigo}")
    assert r.status_code == 200
    detalhe = r.json()
    assert detalhe["dados"]["resultado"]["entrada"]["tipo_frete"] == "Fracionado"
