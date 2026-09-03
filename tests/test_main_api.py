# Desenvolvedor Chefe: RenanFolha

"""
Testes de integração da API (main.py + routers/*) usando o TestClient do
FastAPI, com um banco SQLite temporário e isolado por teste (fixture
`banco_temporario` de conftest.py — nunca toca no frete.db real).

Cobre principalmente autenticação/autorização, que é a parte mais fácil
de quebrar silenciosamente numa mudança futura: login, bloqueio de
tentativas, proteção do último admin e permissão de exclusão de
histórico.
"""

import pytest
from fastapi.testclient import TestClient

import auth_service as auth
import main


@pytest.fixture
def client(banco_temporario):
    with TestClient(main.app) as c:
        yield c


def _login(client, username="admin", senha="admin123"):
    r = client.post("/auth/login", json={"username": username, "senha": senha})
    assert r.status_code == 200, r.text
    return r


def _orcamento_payload(**overrides):
    payload = dict(
        peso=50,
        paletes=[{"comprimento": 40, "largura": 30, "altura": 25}],
        distancia=100,
        valor_mercadoria=1000,
        categoria="Geral",
        transporte="Rodoviário",
        sla="Padrão",
    )
    payload.update(overrides)
    return payload


def test_health(client):
    assert client.get("/health").status_code == 200


def test_orcamento_e_publico_sem_login(client):
    r = client.post("/orcamento", json=_orcamento_payload())
    assert r.status_code == 200
    assert r.json()["resultado"]["frete_total"] > 0


def test_orcamento_repassa_prioridade_rota_pra_memoria_de_calculo(client):
    r = client.post("/orcamento", json=_orcamento_payload(prioridade_rota="Belem"))
    assert r.status_code == 200
    assert r.json()["entrada"]["rota_obrigatoria"] == "Belem"


def test_login_com_admin_padrao(client):
    r = _login(client)
    assert r.json()["role"] == "admin"


def test_login_com_senha_errada(client):
    r = client.post("/auth/login", json={"username": "admin", "senha": "senha-errada"})
    assert r.status_code == 401


def test_login_bloqueia_apos_tentativas_repetidas(client):
    for _ in range(auth._LOGIN_MAX_TENTATIVAS):
        client.post("/auth/login", json={"username": "admin", "senha": "errada"})
    r = client.post("/auth/login", json={"username": "admin", "senha": "errada"})
    assert r.status_code == 429


def test_rotas_admin_exigem_login(client):
    assert client.get("/admin/usuarios").status_code == 401


def test_rotas_admin_exigem_papel_admin(client, monkeypatch):
    # cria um usuário comum e loga com ele
    _login(client)
    client.post("/admin/usuarios", json={
        "nome": "Comum", "username": "comum", "senha": "senha1234", "role": "usuario",
    })
    client.post("/auth/logout")
    _login(client, username="comum", senha="senha1234")
    r = client.get("/admin/usuarios")
    assert r.status_code == 403


def test_criar_usuario_com_senha_curta_e_rejeitado(client):
    _login(client)
    r = client.post("/admin/usuarios", json={
        "nome": "X", "username": "usuariox", "senha": "1234567", "role": "usuario",
    })
    assert r.status_code == 422  # menor que SENHA_MIN_LENGTH (8)


def test_nao_pode_demover_ultimo_admin_ativo(client):
    _login(client)
    r = client.put("/admin/usuarios/1", json={
        "nome": "Administrador", "username": "admin", "role": "usuario", "ativo": True, "senha": "",
    })
    assert r.status_code == 422


def test_nao_pode_excluir_o_proprio_usuario(client):
    _login(client)
    r = client.delete("/admin/usuarios/1")
    assert r.status_code == 422


def test_historico_exige_login(client):
    assert client.get("/historico").status_code == 401
    assert client.post("/historico", json={"cliente": "X", "responsavel": "Y"}).status_code == 401


def test_historico_soh_pode_ser_excluido_pelo_dono_ou_admin(client):
    # admin cria um segundo usuário comum e salva um orçamento logado como admin
    _login(client)
    client.post("/admin/usuarios", json={
        "nome": "Comum", "username": "comum", "senha": "senha1234", "role": "usuario",
    })
    r = client.post("/historico", json={"cliente": "Cliente A", "responsavel": "Admin"})
    assert r.status_code == 200
    codigo = r.json()["codigo"]
    hist_id = next(h["id"] for h in client.get("/historico").json() if h["codigo"] == codigo)

    # o usuário comum não pode excluir o orçamento salvo pelo admin
    client.post("/auth/logout")
    _login(client, username="comum", senha="senha1234")
    r = client.delete(f"/historico/{hist_id}")
    assert r.status_code == 403

    # mas o admin (dono do registro) pode
    client.post("/auth/logout")
    _login(client)
    r = client.delete(f"/historico/{hist_id}")
    assert r.status_code == 200


def test_usuario_comum_pode_excluir_o_proprio_historico(client):
    _login(client)
    client.post("/admin/usuarios", json={
        "nome": "Comum", "username": "comum", "senha": "senha1234", "role": "usuario",
    })
    client.post("/auth/logout")
    _login(client, username="comum", senha="senha1234")
    r = client.post("/historico", json={"cliente": "Cliente B", "responsavel": "Comum"})
    assert r.status_code == 200
    codigo = r.json()["codigo"]
    hist_id = next(h["id"] for h in client.get("/historico").json() if h["codigo"] == codigo)

    r = client.delete(f"/historico/{hist_id}")
    assert r.status_code == 200


def _salvar_historico_com_pedagio(client, pedagio, frete_total, **kwargs):
    payload = {
        "cliente": "Cliente Pedágio", "responsavel": "Admin",
        "frete_total": frete_total,
        "dados": {
            "payload": {"pedagio": pedagio},
            "resultado": {
                "entrada": {}, "calculos_intermediarios": {"pedagio": pedagio},
                "resultado": {"frete_total": frete_total},
            },
        },
    }
    payload.update(kwargs)
    r = client.post("/historico", json=payload)
    assert r.status_code == 200, r.text
    codigo = r.json()["codigo"]
    hist_id = next(h["id"] for h in client.get("/historico").json() if h["codigo"] == codigo)
    return codigo, hist_id


def test_historico_atualizar_pedagio_recalcula_frete_total(client):
    _login(client)
    codigo, hist_id = _salvar_historico_com_pedagio(client, pedagio=10.0, frete_total=100.0)

    r = client.put(f"/historico/{hist_id}/pedagio", json={"pedagio": 25.0})
    assert r.status_code == 200, r.text
    assert r.json()["pedagio"] == 25.0
    assert r.json()["frete_total"] == pytest.approx(115.0)  # 100 - 10 + 25

    detalhe = client.get(f"/historico/{codigo}").json()
    assert detalhe["frete_total"] == pytest.approx(115.0)
    assert detalhe["dados"]["resultado"]["calculos_intermediarios"]["pedagio"] == 25.0
    assert detalhe["dados"]["resultado"]["resultado"]["frete_total"] == pytest.approx(115.0)
    assert detalhe["dados"]["payload"]["pedagio"] == 25.0


def test_historico_atualizar_pedagio_rejeita_valor_negativo(client):
    _login(client)
    _codigo, hist_id = _salvar_historico_com_pedagio(client, pedagio=10.0, frete_total=100.0)
    r = client.put(f"/historico/{hist_id}/pedagio", json={"pedagio": -5.0})
    assert r.status_code == 422


def test_historico_atualizar_pedagio_404_quando_nao_existe(client):
    _login(client)
    r = client.put("/historico/99999/pedagio", json={"pedagio": 10.0})
    assert r.status_code == 404


def test_historico_atualizar_pedagio_soh_pode_ser_feito_pelo_dono_ou_admin(client):
    _login(client)
    client.post("/admin/usuarios", json={
        "nome": "Comum", "username": "comum", "senha": "senha1234", "role": "usuario",
    })
    _codigo, hist_id = _salvar_historico_com_pedagio(client, pedagio=10.0, frete_total=100.0)

    client.post("/auth/logout")
    _login(client, username="comum", senha="senha1234")
    r = client.put(f"/historico/{hist_id}/pedagio", json={"pedagio": 25.0})
    assert r.status_code == 403

    client.post("/auth/logout")
    _login(client)
    r = client.put(f"/historico/{hist_id}/pedagio", json={"pedagio": 25.0})
    assert r.status_code == 200


def test_admin_taxas_balsa_crud(client):
    _login(client)
    veiculo = client.get("/parametros/veiculos").json()[0]["nome"]

    r = client.post("/admin/taxas-balsa", json={
        "cidade_origem": "Belém", "cidade_destino": "Macapá", "veiculo": veiculo,
        "tipo": "fixo", "valor": 120.0,
    })
    assert r.status_code == 200, r.text
    taxa_id = r.json()["id"]

    r = client.get("/admin/taxas-balsa")
    assert r.status_code == 200
    assert any(t["id"] == taxa_id for t in r.json())

    # mesma rota+veiculo de novo -> conflito
    r = client.post("/admin/taxas-balsa", json={
        "cidade_origem": "Belém", "cidade_destino": "Macapá", "veiculo": veiculo,
        "tipo": "fixo", "valor": 130.0,
    })
    assert r.status_code == 409

    r = client.put(f"/admin/taxas-balsa/{taxa_id}", json={
        "cidade_origem": "Belém", "cidade_destino": "Macapá", "veiculo": veiculo,
        "tipo": "fixo", "valor": 150.0,
    })
    assert r.status_code == 200

    r = client.delete(f"/admin/taxas-balsa/{taxa_id}")
    assert r.status_code == 200


def test_admin_faixas_km_veiculo_crud_e_aplicada_no_orcamento(client):
    _login(client)

    payload_orcamento = {
        "peso": 50, "paletes": [{"comprimento": 40, "largura": 30, "altura": 25}],
        "distancia": 100, "valor_mercadoria": 1000,
        "categoria": (client.get("/parametros/categorias").json())[0]["nome"],
        "transporte": (client.get("/parametros/transportes").json())[0]["nome"],
        "sla": (client.get("/parametros/slas").json())[0]["nome"],
    }
    # descobre qual veículo o peso/paletes de teste escolhem antes de
    # cadastrar a faixa (a escolha automática não segue a ordem de
    # /parametros/veiculos)
    r = client.post("/orcamento", json=payload_orcamento)
    assert r.status_code == 200, r.text
    veiculo_escolhido = r.json()["entrada"]["veiculo"]
    assert r.json()["calculos_intermediarios"]["faixa_km_aplicada"] is False

    r = client.post("/admin/faixas-km-veiculo", json={
        "veiculo": veiculo_escolhido, "de": 0, "ate": 999999, "tarifa_km": 0.01,
    })
    assert r.status_code == 200, r.text
    faixa_id = r.json()["id"]

    r = client.get("/admin/faixas-km-veiculo")
    assert r.status_code == 200
    assert any(f["id"] == faixa_id for f in r.json())

    # a faixa recém-cadastrada (tarifa quase zero) já deve valer no
    # próximo /orcamento, sem precisar de /admin/reload manual
    r = client.post("/orcamento", json=payload_orcamento)
    assert r.status_code == 200, r.text
    calc = r.json()["calculos_intermediarios"]
    assert calc["faixa_km_aplicada"] is True
    assert calc["tarifa_km_veiculo"] == 0.01

    r = client.put(f"/admin/faixas-km-veiculo/{faixa_id}", json={
        "veiculo": veiculo_escolhido, "de": 0, "ate": 999999, "tarifa_km": 0.02,
    })
    assert r.status_code == 200

    r = client.delete(f"/admin/faixas-km-veiculo/{faixa_id}")
    assert r.status_code == 200


def test_admin_taxas_balsa_exige_admin(client):
    r = client.get("/admin/taxas-balsa")
    assert r.status_code == 401


def test_admin_prioridades_rota_crud(client):
    _login(client)
    filial = client.get("/parametros/filiais").json()[0]["nome"]

    r = client.post("/admin/prioridades-rota", json={
        "estado_origem": "*", "cidade_destino": "Manaus", "filial_escala": filial,
    })
    assert r.status_code == 200, r.text
    prioridade_id = r.json()["id"]

    r = client.get("/admin/prioridades-rota")
    assert r.status_code == 200
    assert any(e["id"] == prioridade_id for e in r.json())

    # mesma rota de novo -> conflito
    r = client.post("/admin/prioridades-rota", json={
        "estado_origem": "*", "cidade_destino": "Manaus", "filial_escala": filial,
    })
    assert r.status_code == 409

    r = client.put(f"/admin/prioridades-rota/{prioridade_id}", json={
        "estado_origem": "*", "cidade_destino": "Manaus", "filial_escala": filial,
        "observacao": "ajustada",
    })
    assert r.status_code == 200

    r = client.delete(f"/admin/prioridades-rota/{prioridade_id}")
    assert r.status_code == 200


def test_admin_prioridades_rota_exige_admin(client):
    r = client.get("/admin/prioridades-rota")
    assert r.status_code == 401


def test_geo_distancia_descobre_veiculo_a_partir_de_peso_e_paletes(client, monkeypatch):
    """peso/paletes/transporte em /geo/distancia não entram no cálculo de
    frete -- servem só pra descobrir qual veículo seria escolhido, pra
    permitir reaproveitar uma rota já cotada no histórico com esse mesmo
    veículo (ver geo_service._buscar_rota_no_historico)."""
    import routers.geo as geo_router

    capturado = {}

    async def _calcular_distancia_fake(origem, destino, veiculo=None):
        capturado["veiculo"] = veiculo
        return {"distancia_km": 10, "duracao_min": 10, "pedagio_valor": None, "pedagio_moeda": None,
                "origem_resolvido": origem, "destino_resolvido": destino}

    monkeypatch.setattr(geo_router.geo, "calcular_distancia", _calcular_distancia_fake)

    r = client.post("/geo/distancia", json={
        "origem": "Campinas, SP", "destino": "São Paulo, SP",
        "peso": 50, "paletes": [{"comprimento": 40, "largura": 30, "altura": 25}],
        "transporte": "Rodoviário",
    })
    assert r.status_code == 200
    assert capturado["veiculo"] == "Caminhonete"  # peso baixo -> menor veículo da faixa padrão


def test_geo_distancia_sem_peso_nao_descobre_veiculo(client, monkeypatch):
    import routers.geo as geo_router

    capturado = {}

    async def _calcular_distancia_fake(origem, destino, veiculo=None):
        capturado["veiculo"] = veiculo
        return {"distancia_km": 10, "duracao_min": 10, "pedagio_valor": None, "pedagio_moeda": None,
                "origem_resolvido": origem, "destino_resolvido": destino}

    monkeypatch.setattr(geo_router.geo, "calcular_distancia", _calcular_distancia_fake)

    r = client.post("/geo/distancia", json={"origem": "Campinas, SP", "destino": "São Paulo, SP"})
    assert r.status_code == 200
    assert capturado["veiculo"] is None
