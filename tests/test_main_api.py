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


def test_orcamento_margem_30_recusada_sem_login(client):
    r = client.post("/orcamento", json=_orcamento_payload(margem_lucro_pct=30))
    assert r.status_code == 403


def test_orcamento_margem_30_recusada_pra_usuario_comum(client):
    _login(client)
    client.post("/admin/usuarios", json={
        "nome": "Comum", "username": "comum", "senha": "senha1234", "role": "usuario",
    })
    client.post("/auth/logout")
    _login(client, username="comum", senha="senha1234")
    r = client.post("/orcamento", json=_orcamento_payload(margem_lucro_pct=30))
    assert r.status_code == 403


def test_orcamento_margem_30_permitida_pra_admin_logado(client):
    _login(client)
    r = client.post("/orcamento", json=_orcamento_payload(margem_lucro_pct=30))
    assert r.status_code == 200
    assert r.json()["calculos_intermediarios"]["margem_lucro_pct"] == 30


def test_orcamento_margens_40_e_50_continuam_publicas_sem_login(client):
    for margem in (40, 50):
        r = client.post("/orcamento", json=_orcamento_payload(margem_lucro_pct=margem))
        assert r.status_code == 200


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


def test_usuario_comum_so_ve_o_proprio_historico_na_listagem(client):
    _login(client)
    client.post("/admin/usuarios", json={
        "nome": "Comum", "username": "comum", "senha": "senha1234", "role": "usuario",
    })
    client.post("/historico", json={"cliente": "Cliente Admin", "responsavel": "Admin"})

    client.post("/auth/logout")
    _login(client, username="comum", senha="senha1234")
    r_comum = client.post("/historico", json={"cliente": "Cliente Comum", "responsavel": "Comum"})
    codigo_comum = r_comum.json()["codigo"]

    # usuário comum só vê o próprio orçamento na listagem, não o do admin
    listagem = client.get("/historico").json()
    assert [h["codigo"] for h in listagem] == [codigo_comum]

    client.post("/auth/logout")
    _login(client)
    # admin continua vendo os dois
    listagem_admin = client.get("/historico").json()
    assert len(listagem_admin) == 2


def test_usuario_comum_nao_ve_detalhe_de_historico_de_outro(client):
    _login(client)
    client.post("/admin/usuarios", json={
        "nome": "Comum", "username": "comum", "senha": "senha1234", "role": "usuario",
    })
    r = client.post("/historico", json={"cliente": "Cliente Admin", "responsavel": "Admin"})
    codigo_admin = r.json()["codigo"]

    client.post("/auth/logout")
    _login(client, username="comum", senha="senha1234")
    assert client.get(f"/historico/{codigo_admin}").status_code == 403
    assert client.get(f"/historico/{codigo_admin}/planilha").status_code == 403

    client.post("/auth/logout")
    _login(client)
    assert client.get(f"/historico/{codigo_admin}").status_code == 200


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


def test_historico_atualizar_pedagio_registra_alteracao(client):
    _login(client)
    codigo, hist_id = _salvar_historico_com_pedagio(client, pedagio=10.0, frete_total=100.0)

    detalhe_antes = client.get(f"/historico/{codigo}").json()
    assert detalhe_antes["alteracoes"] == []

    r = client.put(f"/historico/{hist_id}/pedagio", json={"pedagio": 25.0})
    assert r.status_code == 200, r.text

    detalhe = client.get(f"/historico/{codigo}").json()
    assert len(detalhe["alteracoes"]) == 1
    alteracao = detalhe["alteracoes"][0]
    assert alteracao["campo"] == "pedagio"
    assert alteracao["valor_antigo"] == pytest.approx(10.0)
    assert alteracao["valor_novo"] == pytest.approx(25.0)
    assert alteracao["alterado_por"] == "admin"
    assert alteracao["alterado_em"]


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


def test_admin_pracas_pedagio_crud(client):
    _login(client)

    r = client.post("/admin/pracas-pedagio", json={
        "nome": "Praça 5", "rodovia": "BR-101", "concessionaria": "ViaSul",
        "valor_eixo_2": 12.4, "valor_eixo_3": 18.6,
    })
    assert r.status_code == 200, r.text
    praca_id = r.json()["id"]

    r = client.get("/admin/pracas-pedagio")
    assert r.status_code == 200
    assert any(p["id"] == praca_id for p in r.json())

    r = client.get("/parametros/pracas-pedagio")
    assert r.status_code == 200
    assert any(p["id"] == praca_id for p in r.json())

    # mesmo nome + rodovia de novo -> conflito
    r = client.post("/admin/pracas-pedagio", json={
        "nome": "Praça 5", "rodovia": "BR-101", "concessionaria": "Outra",
    })
    assert r.status_code == 409

    r = client.put(f"/admin/pracas-pedagio/{praca_id}", json={
        "nome": "Praça 5", "rodovia": "BR-101", "concessionaria": "ViaSul", "valor_eixo_2": 15.0,
    })
    assert r.status_code == 200

    r = client.delete(f"/admin/pracas-pedagio/{praca_id}")
    assert r.status_code == 200


def test_admin_pracas_pedagio_exige_admin(client):
    r = client.get("/admin/pracas-pedagio")
    assert r.status_code == 401


def test_admin_pracas_pedagio_nao_exclui_praca_em_uso(client):
    _login(client)
    r = client.post("/admin/pracas-pedagio", json={
        "nome": "Praça 5", "rodovia": "BR-101", "concessionaria": "ViaSul",
    })
    praca_id = r.json()["id"]
    client.post("/admin/pedagios-rota", json={
        "cidade_origem": "Curitiba", "cidade_destino": "Florianópolis", "praca_id": praca_id,
    })

    r = client.delete(f"/admin/pracas-pedagio/{praca_id}")
    assert r.status_code == 409


def test_admin_pracas_pedagio_importar_csv(client):
    _login(client)
    csv = (
        "nome,rodovia,concessionaria,valor_eixo_2\n"
        "Praça 5,BR-101,ViaSul,12.4\n"
        "Praça 8,BR-101,ViaSul,10.0\n"
    )
    r = client.post("/admin/pracas-pedagio/importar-csv", json={"conteudo": csv})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["criadas"] == 2
    assert data["erros"] == []
    assert len(client.get("/admin/pracas-pedagio").json()) == 2


def test_admin_pedagios_rota_crud(client):
    _login(client)
    praca_id = client.post("/admin/pracas-pedagio", json={
        "nome": "Praça 5", "rodovia": "BR-101", "concessionaria": "ViaSul", "valor_eixo_2": 12.4,
    }).json()["id"]

    r = client.post("/admin/pedagios-rota", json={
        "cidade_origem": "Curitiba", "cidade_destino": "Florianópolis", "praca_id": praca_id,
    })
    assert r.status_code == 200, r.text
    pedagio_id = r.json()["id"]

    r = client.get("/admin/pedagios-rota")
    assert r.status_code == 200
    linha = next(p for p in r.json() if p["id"] == pedagio_id)
    assert linha["praca_nome"] == "Praça 5"

    # mesmo corredor + praça de novo -> conflito
    r = client.post("/admin/pedagios-rota", json={
        "cidade_origem": "Curitiba", "cidade_destino": "Florianópolis", "praca_id": praca_id,
    })
    assert r.status_code == 409

    r = client.put(f"/admin/pedagios-rota/{pedagio_id}", json={
        "cidade_origem": "Curitiba", "cidade_destino": "Florianópolis", "praca_id": praca_id,
        "observacao": "ajustado",
    })
    assert r.status_code == 200

    r = client.delete(f"/admin/pedagios-rota/{pedagio_id}")
    assert r.status_code == 200


def test_admin_pedagios_rota_exige_admin(client):
    r = client.get("/admin/pedagios-rota")
    assert r.status_code == 401


def test_admin_distancias_fixas_crud(client):
    _login(client)

    r = client.post("/admin/distancias-fixas", json={
        "cidade_origem": "Belem", "cidade_destino": "Manaus", "distancia_km": 2096,
    })
    assert r.status_code == 200, r.text
    id_ = r.json()["id"]

    r = client.get("/admin/distancias-fixas")
    assert r.status_code == 200
    assert any(d["id"] == id_ for d in r.json())

    # mesmo corredor de novo -> conflito
    r = client.post("/admin/distancias-fixas", json={
        "cidade_origem": "Belem", "cidade_destino": "Manaus", "distancia_km": 2100,
    })
    assert r.status_code == 409

    r = client.put(f"/admin/distancias-fixas/{id_}", json={
        "cidade_origem": "Belem", "cidade_destino": "Manaus", "distancia_km": 2100,
        "observacao": "ajustada",
    })
    assert r.status_code == 200

    r = client.delete(f"/admin/distancias-fixas/{id_}")
    assert r.status_code == 200


def test_admin_distancias_fixas_exige_admin(client):
    r = client.get("/admin/distancias-fixas")
    assert r.status_code == 401


def test_admin_veiculos_aceita_numero_eixos(client):
    _login(client)
    veiculo = client.get("/admin/veiculos").json()[0]  # dict cru do banco, já vem com "id"
    r = client.put(f"/admin/veiculos/{veiculo['id']}", json={
        "nome": veiculo["nome"], "de": veiculo["de"], "ate": veiculo["ate"],
        "tarifa_km": veiculo["tarifa_km"], "valor_tonelada_excedente": veiculo["valor_tonelada_excedente"],
        "numero_eixos": 2,
    })
    assert r.status_code == 200, r.text
    atualizado = next(v for v in client.get("/admin/veiculos").json() if v["id"] == veiculo["id"])
    assert atualizado["numero_eixos"] == 2


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


def test_admin_banco_dados_exige_admin(client):
    assert client.get("/admin/banco-dados").status_code == 401
    assert client.post("/admin/banco-dados/testar", json={"tipo": "sqlite"}).status_code == 401
    assert client.post("/admin/banco-dados/aplicar", json={"tipo": "sqlite"}).status_code == 401


def test_admin_banco_dados_get_nao_devolve_senha(client):
    _login(client)
    r = client.get("/admin/banco-dados")
    assert r.status_code == 200
    data = r.json()
    assert data["tipo"] == "sqlite"
    assert "senha" not in data
    assert data["senha_configurada"] is False


def test_admin_banco_dados_testar_driver_ausente_da_422(client):
    # Mesmo raciocínio de test_conectar_sem_driver_instalado_da_erro_amigavel
    # em test_db_conexao.py: só faz sentido testar o fallback de driver
    # ausente se o psycopg2 de fato não estiver instalado neste ambiente.
    import importlib
    try:
        importlib.import_module("psycopg2")
    except ImportError:
        pass
    else:
        pytest.skip("psycopg2 está instalado neste ambiente — o teste de driver ausente não se aplica")

    _login(client)
    r = client.post("/admin/banco-dados/testar", json={
        "tipo": "postgresql", "host": "x", "porta": 5432, "banco": "x", "usuario": "x", "senha": "x",
    })
    assert r.status_code == 422
    assert "psycopg2" in r.json()["detail"]


def test_admin_banco_dados_aplicar_sqlite_para_sqlite_migra_tudo(client, tmp_path):
    """Único cenário de troca de banco testável de ponta a ponta neste
    ambiente (sem SQL Server/MySQL/PostgreSQL disponíveis): sqlite ->
    outro arquivo sqlite. Cobre o fluxo inteiro do endpoint /aplicar
    (criar schema no destino, exportar do atual, importar no destino,
    trocar a config ativa, recarregar parâmetros)."""
    _login(client)

    # cadastra uma praça de pedágio pra ter dado "customizado" (além do
    # seed padrão) que precisa sobreviver à migração
    r = client.post("/admin/pracas-pedagio", json={
        "nome": "Praça Migração", "rodovia": "BR-101", "concessionaria": "ViaSul", "valor_eixo_2": 42.0,
    })
    assert r.status_code == 200, r.text

    destino = str(tmp_path / "destino_migrado.db")
    r = client.post("/admin/banco-dados/aplicar", json={"tipo": "sqlite", "sqlite_path": destino})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["linhas_migradas"]["pracas_pedagio"] == 1
    assert data["linhas_migradas"]["filiais"] > 0  # dados de exemplo semeados na origem

    # a API já deve estar usando o banco novo, sem precisar reiniciar
    r = client.get("/admin/banco-dados")
    assert r.json()["tipo"] == "sqlite"
    assert r.json()["sqlite_path"] == destino

    r = client.get("/admin/pracas-pedagio")
    assert any(p["nome"] == "Praça Migração" for p in r.json())

    # o arquivo novo existe de fato e tem os dados
    import sqlite3
    conn = sqlite3.connect(destino)
    try:
        assert conn.execute("SELECT COUNT(*) FROM pracas_pedagio").fetchone()[0] == 1
    finally:
        conn.close()
