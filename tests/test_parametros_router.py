# Desenvolvedor Chefe: RenanFolha

"""
Testes de integração das rotas públicas de leitura em routers/parametros.py
(sem login) — usadas pra montar os campos de seleção da tela de orçamento.
Algumas (categorias, transportes, slas, filiais, veículos, pracas-pedagio)
já eram exercitadas em outros arquivos; este cobre as que ainda não
tinham nenhum teste.
"""

from conftest import _login


def test_parametros_taxas_adicionais(client):
    r = client.get("/parametros/taxas-adicionais")
    assert r.status_code == 200
    dados = r.json()
    assert len(dados) > 0  # seed padrão cadastra GRIS, Ad Valorem etc.
    assert {"nome", "tipo", "valor"} <= dados[0].keys()


def test_parametros_tipos_frete(client):
    r = client.get("/parametros/tipos-frete")
    assert r.status_code == 200
    assert "Fracionado" in r.json()


def test_parametros_faixas_peso_sem_filtro(client):
    r = client.get("/parametros/faixas-peso")
    assert r.status_code == 200
    dados = r.json()
    assert len(dados) > 0
    assert {"tipo_frete", "de", "ate", "tarifa_base", "custo_kg_adicional"} <= dados[0].keys()


def test_parametros_faixas_peso_filtra_por_tipo_frete(client):
    todas = client.get("/parametros/faixas-peso").json()
    filtradas = client.get("/parametros/faixas-peso", params={"tipo_frete": "Fracionado"}).json()
    assert 0 < len(filtradas) <= len(todas)
    assert all(f["tipo_frete"] == "Fracionado" for f in filtradas)


def test_parametros_faixas_distancia_sem_filtro(client):
    r = client.get("/parametros/faixas-distancia")
    assert r.status_code == 200
    dados = r.json()
    assert len(dados) > 0
    assert {"tipo_frete", "de", "ate", "taxa_fixa", "tarifa_km"} <= dados[0].keys()


def test_parametros_faixas_distancia_filtra_por_tipo_frete(client):
    todas = client.get("/parametros/faixas-distancia").json()
    filtradas = client.get("/parametros/faixas-distancia", params={"tipo_frete": "Fracionado"}).json()
    assert 0 < len(filtradas) <= len(todas)
    assert all(f["tipo_frete"] == "Fracionado" for f in filtradas)


def test_parametros_faixas_coleta(client):
    r = client.get("/parametros/faixas-coleta")
    assert r.status_code == 200
    dados = r.json()
    assert len(dados) > 0  # seed padrão cadastra faixas de coleta por km
    assert {"de", "ate", "taxa_fixa", "tarifa_km"} <= dados[0].keys()


def test_parametros_transportadoras_terceirizadas(client):
    assert client.get("/parametros/transportadoras-terceirizadas").json() == []

    _login(client)
    client.post("/admin/transportadoras-terceirizadas", json={
        "nome": "Transp Teste", "cidade": "Curitiba", "tipo": "ambos", "valor": 300.0,
    })

    r = client.get("/parametros/transportadoras-terceirizadas")
    assert r.status_code == 200
    assert any(t["nome"] == "Transp Teste" for t in r.json())
