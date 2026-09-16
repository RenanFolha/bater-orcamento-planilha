# Desenvolvedor Chefe: RenanFolha

"""
Testes de integração das rotas /admin/* de routers/admin_precos.py (tela
"Tabela de Preços") que ainda não tinham cobertura no nível de API --
o cálculo/CRUD de cada tabela já era testado direto em frete_db.py (ver
tests/test_frete_db_*.py), mas o roteamento HTTP em si (conflito 409,
"não pode excluir a última linha" etc. por cima do helper genérico de
deps.py) não passava por nenhum teste.
"""

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


def test_admin_reload_parametros(client):
    _login(client)
    r = client.post("/admin/reload")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok"


def test_admin_filiais_crud(client):
    _login(client)

    r = client.post("/admin/filiais", json={"nome": "Filial Teste", "endereco": "Rua X, 1", "uf": "SP"})
    assert r.status_code == 200, r.text
    filial_id = r.json()["id"]

    r = client.get("/admin/filiais")
    assert r.status_code == 200
    assert any(f["id"] == filial_id for f in r.json())

    r = client.post("/admin/filiais", json={"nome": "Filial Teste", "endereco": "Rua Y, 2", "uf": "RJ"})
    assert r.status_code == 409

    r = client.put(f"/admin/filiais/{filial_id}", json={"nome": "Filial Teste", "endereco": "Rua Z, 3", "uf": "MG"})
    assert r.status_code == 200
    assert next(f for f in client.get("/admin/filiais").json() if f["id"] == filial_id)["uf"] == "MG"

    r = client.delete(f"/admin/filiais/{filial_id}")
    assert r.status_code == 200


def test_admin_veiculos_post_e_delete(client):
    # PUT já é coberto por test_admin_veiculos_aceita_numero_eixos (ver
    # tests/test_main_api.py) -- este cobre POST (criação) e DELETE.
    _login(client)

    r = client.post("/admin/veiculos", json={
        "nome": "Veiculo Teste", "de": 0, "ate": 500, "tarifa_km": 3.0, "valor_tonelada_excedente": 100.0,
    })
    assert r.status_code == 200, r.text
    veiculo_id = r.json()["id"]

    r = client.delete(f"/admin/veiculos/{veiculo_id}")
    assert r.status_code == 200


def test_admin_taxas_adicionais_crud(client):
    _login(client)

    r = client.post("/admin/taxas-adicionais", json={"nome": "Taxa X", "tipo": "fixo", "valor": 10.0})
    assert r.status_code == 200, r.text
    taxa_id = r.json()["id"]

    r = client.get("/admin/taxas-adicionais")
    assert any(t["id"] == taxa_id for t in r.json())

    r = client.post("/admin/taxas-adicionais", json={"nome": "Taxa X", "tipo": "fixo", "valor": 20.0})
    assert r.status_code == 409

    r = client.put(f"/admin/taxas-adicionais/{taxa_id}", json={"nome": "Taxa X", "tipo": "percentual", "valor": 5.0})
    assert r.status_code == 200

    r = client.delete(f"/admin/taxas-adicionais/{taxa_id}")
    assert r.status_code == 200


def test_admin_coleta_cidades_fixas_crud(client):
    _login(client)
    filial = client.get("/parametros/filiais").json()[0]["nome"]
    veiculo = client.get("/parametros/veiculos").json()[0]["nome"]

    payload = {"filial_origem": filial, "cidade_destino": "Osasco", "veiculo": veiculo, "valor_fixo": 150.0}
    r = client.post("/admin/coleta-cidades-fixas", json=payload)
    assert r.status_code == 200, r.text
    linha_id = r.json()["id"]

    r = client.get("/admin/coleta-cidades-fixas")
    assert any(c["id"] == linha_id for c in r.json())

    # mesma cidade na mesma filial+veículo -> conflito (mensagem vem de
    # frete_db.py via msg_conflito=str, ver routers/admin_precos.py)
    r = client.post("/admin/coleta-cidades-fixas", json=payload)
    assert r.status_code == 409
    assert "Osasco" in r.json()["detail"]

    payload_editado = {**payload, "valor_fixo": 200.0}
    r = client.put(f"/admin/coleta-cidades-fixas/{linha_id}", json=payload_editado)
    assert r.status_code == 200

    r = client.delete(f"/admin/coleta-cidades-fixas/{linha_id}")
    assert r.status_code == 200


def test_admin_taxas_regionais_crud(client):
    _login(client)

    payload = {"cidade": "Manaus", "nome": "Taxa Teste", "tipo": "fixo", "valor": 100.0}
    r = client.post("/admin/taxas-regionais", json=payload)
    assert r.status_code == 200, r.text
    taxa_id = r.json()["id"]

    r = client.get("/admin/taxas-regionais")
    assert any(t["id"] == taxa_id for t in r.json())

    # mesma cidade cadastrada de novo pra mesma taxa (nome igual) ->
    # conflito (a checagem em frete_db.py é por nome da taxa + cidade)
    r = client.post("/admin/taxas-regionais", json={**payload, "valor": 200.0})
    assert r.status_code == 409
    assert "Manaus" in r.json()["detail"]

    r = client.put(f"/admin/taxas-regionais/{taxa_id}", json={**payload, "valor": 150.0})
    assert r.status_code == 200

    r = client.delete(f"/admin/taxas-regionais/{taxa_id}")
    assert r.status_code == 200


def test_admin_aliquotas_icms_crud(client):
    _login(client)

    payload = {"estado_origem": "SP", "estado_destino": "RJ", "aliquota": 12.0}
    r = client.post("/admin/aliquotas-icms", json=payload)
    assert r.status_code == 200, r.text
    aliquota_id = r.json()["id"]

    r = client.get("/admin/aliquotas-icms")
    assert any(a["id"] == aliquota_id for a in r.json())

    r = client.post("/admin/aliquotas-icms", json=payload)
    assert r.status_code == 409

    r = client.put(f"/admin/aliquotas-icms/{aliquota_id}", json={**payload, "aliquota": 7.0})
    assert r.status_code == 200

    r = client.delete(f"/admin/aliquotas-icms/{aliquota_id}")
    assert r.status_code == 200


def test_admin_pis_cofins_get_e_put(client):
    _login(client)

    r = client.get("/admin/pis-cofins")
    assert r.status_code == 200, r.text

    r = client.put("/admin/pis-cofins", json={"aliquota": 9.25, "observacao": "teste"})
    assert r.status_code == 200, r.text
    assert r.json()["aliquota"] == 9.25

    assert client.get("/admin/pis-cofins").json()["aliquota"] == 9.25


def test_admin_transportadoras_terceirizadas_crud(client):
    _login(client)

    payload = {"nome": "Transp Teste", "cidade": "Curitiba", "tipo": "ambos", "valor": 300.0}
    r = client.post("/admin/transportadoras-terceirizadas", json=payload)
    assert r.status_code == 200, r.text
    transp_id = r.json()["id"]

    r = client.get("/admin/transportadoras-terceirizadas")
    assert any(t["id"] == transp_id for t in r.json())

    r = client.post("/admin/transportadoras-terceirizadas", json=payload)
    assert r.status_code == 409

    r = client.put(f"/admin/transportadoras-terceirizadas/{transp_id}", json={**payload, "valor": 350.0})
    assert r.status_code == 200

    r = client.delete(f"/admin/transportadoras-terceirizadas/{transp_id}")
    assert r.status_code == 200


def test_admin_faixas_coleta_crud(client):
    _login(client)

    payload = {"de": 500, "ate": 600, "taxa_fixa": 80.0, "tarifa_km": 1.5}
    r = client.post("/admin/faixas-coleta", json=payload)
    assert r.status_code == 200, r.text
    faixa_id = r.json()["id"]

    r = client.get("/admin/faixas-coleta")
    assert any(f["id"] == faixa_id for f in r.json())

    r = client.put(f"/admin/faixas-coleta/{faixa_id}", json={**payload, "taxa_fixa": 90.0})
    assert r.status_code == 200

    r = client.delete(f"/admin/faixas-coleta/{faixa_id}")
    assert r.status_code == 200


def test_admin_categorias_crud(client):
    _login(client)

    r = client.post("/admin/categorias", json={"nome": "Categoria Teste", "multiplicador": 1.2})
    assert r.status_code == 200, r.text
    cat_id = r.json()["id"]

    r = client.get("/admin/categorias")
    assert any(c["id"] == cat_id for c in r.json())

    r = client.post("/admin/categorias", json={"nome": "Categoria Teste", "multiplicador": 1.5})
    assert r.status_code == 409

    r = client.put(f"/admin/categorias/{cat_id}", json={"nome": "Categoria Teste", "multiplicador": 1.3})
    assert r.status_code == 200

    r = client.delete(f"/admin/categorias/{cat_id}")
    assert r.status_code == 200


def test_admin_transportes_crud(client):
    _login(client)

    payload = {"nome": "Transporte Teste", "multiplicador": 1.1, "fator_cubagem": 250}
    r = client.post("/admin/transportes", json=payload)
    assert r.status_code == 200, r.text
    transp_id = r.json()["id"]

    r = client.get("/admin/transportes")
    assert any(t["id"] == transp_id for t in r.json())

    r = client.post("/admin/transportes", json=payload)
    assert r.status_code == 409

    r = client.put(f"/admin/transportes/{transp_id}", json={**payload, "multiplicador": 1.2})
    assert r.status_code == 200

    r = client.delete(f"/admin/transportes/{transp_id}")
    assert r.status_code == 200


def test_admin_slas_crud(client):
    _login(client)

    payload = {"nome": "SLA Teste", "multiplicador": 1.4, "prazo_dias": 3}
    r = client.post("/admin/slas", json=payload)
    assert r.status_code == 200, r.text
    sla_id = r.json()["id"]

    r = client.get("/admin/slas")
    assert any(s["id"] == sla_id for s in r.json())

    r = client.post("/admin/slas", json=payload)
    assert r.status_code == 409

    r = client.put(f"/admin/slas/{sla_id}", json={**payload, "prazo_dias": 2})
    assert r.status_code == 200

    r = client.delete(f"/admin/slas/{sla_id}")
    assert r.status_code == 200
