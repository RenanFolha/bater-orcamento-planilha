# Desenvolvedor Chefe: RenanFolha

"""Testes de integração do orçamento Fracionado (POST /orcamento/fracionado)
e do CRUD administrativo das faixas de peso/distância que alimentam o
frete base dele (ver frete_service.calcular_orcamento_fracionado)."""

import pytest
from conftest import _login


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


def test_orcamento_fracionado_icms_configurado_acima_de_100_da_500(client):
    # Mesmo raciocínio de test_orcamento_icms_configurado_acima_de_100_da_500
    # em test_main_api.py (ICMS é gross-up "por dentro" -- FreteConfigError
    # -> 500, ver routers/orcamento_fracionado.py) -- o Fracionado tem sua
    # própria cópia do try/except, então precisa do próprio teste pra cobrir.
    # Cadastra (ou atualiza, se já existir -- o seed padrão só tem
    # "SP -> *" genérica, não "SP -> RJ" específica) a linha específica
    # SP->RJ, que vence a genérica por especificidade (ver
    # aliquota_icms_aplicavel).
    import frete_db as db
    import frete_service as fs

    existente = next(
        (a for a in db.listar_aliquotas_icms_admin() if a["estado_origem"] == "SP" and a["estado_destino"] == "RJ"),
        None,
    )
    if existente:
        aliquota_original = existente["aliquota"]
        db.atualizar_aliquota_icms(existente["id"], "SP", "RJ", 150.0, "teste: aliquota invalida")
        id_criado = None
    else:
        id_criado = db.inserir_aliquota_icms("SP", "RJ", 150.0, "teste: aliquota invalida")
    fs.carregar_parametros()
    try:
        r = client.post(
            "/orcamento/fracionado",
            json=_payload(cidade_origem="São Paulo, SP, Brasil", cidade_destino="Rio de Janeiro, RJ, Brasil"),
        )
        assert r.status_code == 500
        assert "config" in r.json()["detail"].lower()
    finally:
        if existente:
            db.atualizar_aliquota_icms(existente["id"], "SP", "RJ", aliquota_original, existente["observacao"])
        else:
            db.excluir_aliquota_icms(id_criado)
        fs.carregar_parametros()


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


def test_orcamento_fracionado_ignora_margem_lucro_pct_enviado_no_payload(client):
    # Margem de lucro não é mais digitável (fixa em 40%, ver
    # fs.MARGEM_LUCRO_PADRAO) -- mesmo enviando o campo, é ignorado.
    r = client.post("/orcamento/fracionado", json=_payload(margem_lucro_pct=30))
    assert r.status_code == 200, r.text
    assert r.json()["calculos_intermediarios"]["margem_lucro_pct"] == 40


def test_orcamento_fracionado_gris_pct_digitado_substitui_o_cadastrado(client):
    r = client.post("/orcamento/fracionado", json=_payload(gris_pct=5.0))
    assert r.status_code == 200, r.text
    gris = next(t for t in r.json()["calculos_intermediarios"]["taxas_adicionais"] if t["nome"] == "GRIS")
    assert gris["valor_configurado"] == pytest.approx(5.0)


def test_orcamento_fracionado_gris_pct_abaixo_do_cadastrado_da_422(client):
    r = client.post("/orcamento/fracionado", json=_payload(gris_pct=0.1))
    assert r.status_code == 422
    assert "GRIS" in r.json()["detail"]


def test_orcamento_fracionado_piso_markup_minimo_ajusta_impostos_e_taxas(client):
    # Mesmo mecanismo de test_orcamento_piso_markup_minimo_ajusta_impostos_e_taxas
    # em test_main_api.py, aqui pro Fracionado.
    r = client.post("/orcamento/fracionado", json=_payload(valor_mercadoria=100000, ad_valorem_pct=50.0))
    assert r.status_code == 200, r.text
    calc = r.json()["calculos_intermediarios"]
    assert calc["ajuste_piso_markup"] > 0
    base_piso = calc["total_custo_operacao"] + calc["total_impostos_taxas"] - calc["ajuste_piso_markup"]
    piso = round(base_piso * 1.4, 2)
    assert r.json()["resultado"]["frete_total"] == pytest.approx(piso, abs=0.05)


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

    r = client.put(f"/admin/faixas-distancia-fracionado/{novo_id}", json={
        "de": 5000, "ate": 999999, "taxa_fixa": 550.0, "tarifa_km": 1.2, "observacao": "teste editado",
    })
    assert r.status_code == 200, r.text

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
