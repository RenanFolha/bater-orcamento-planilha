# Desenvolvedor Chefe: RenanFolha

"""
Testes de geo_service._buscar_rota_no_historico / calcular_distancia:
antes de chamar o serviço externo de geolocalização, uma rota (por
cidade, nas duas direções) E o mesmo veículo já cotados juntos e salvos
no histórico devem ser reaproveitados em vez de gastar uma
geocodificação nova. Usa o fixture `banco_temporario` (conftest.py) —
nunca toca no frete.db real nem em rede de verdade.
"""

import asyncio

import httpx
import pytest

import frete_db as db
import frete_service as fs
import geo_service as geo


def _salvar_rota(origem_resumo, destino_resumo, distancia_km, veiculo="VUC"):
    db.salvar_orcamento_historico(
        cliente="Cliente Teste", responsavel="Teste",
        origem_resumo=origem_resumo, destino_resumo=destino_resumo,
        veiculo=veiculo, distancia_km=distancia_km, valor_mercadoria=0,
        frete_total=0, dados_json="{}",
    )


def test_rota_nao_encontrada_quando_historico_vazio(banco_temporario):
    assert geo._buscar_rota_no_historico("Campinas", "Belém, PA, Brasil", "VUC") is None


def test_encontra_rota_ja_cotada_mesma_direcao_e_veiculo(banco_temporario):
    _salvar_rota("Campinas", "Belém, Pará, Brasil", 2900, veiculo="VUC")
    achado = geo._buscar_rota_no_historico("Campinas", "Rua X, 100, Belém, Pará, Brasil", "VUC")
    assert achado is not None
    assert achado["distancia_km"] == 2900


def test_encontra_rota_ja_cotada_direcao_invertida(banco_temporario):
    # negócio trata ida/volta como a mesma distância (ver tabela de frete,
    # rotas "vice-versa") -- buscar Belém->Campinas deve achar uma
    # cotação salva como Campinas->Belém.
    _salvar_rota("Campinas", "Belém, Pará, Brasil", 2900, veiculo="Carreta")
    achado = geo._buscar_rota_no_historico("Rua Y, 1, Belém, Pará, Brasil", "Campinas", "Carreta")
    assert achado is not None
    assert achado["distancia_km"] == 2900


def test_nao_confunde_cidade_diferente(banco_temporario):
    _salvar_rota("Campinas", "Belém, Pará, Brasil", 2900)
    assert geo._buscar_rota_no_historico("Campinas", "Curitiba, Paraná, Brasil", "VUC") is None


def test_nao_reaproveita_veiculo_diferente(banco_temporario):
    # mesma rota, mas cotada antes com Carreta -- pedindo VUC não pode achar
    _salvar_rota("Campinas", "Belém, Pará, Brasil", 2900, veiculo="Carreta")
    assert geo._buscar_rota_no_historico("Campinas", "Belém, Pará, Brasil", "VUC") is None


def test_sem_veiculo_informado_nunca_reaproveita(banco_temporario):
    _salvar_rota("Campinas", "Belém, Pará, Brasil", 2900, veiculo="VUC")
    assert geo._buscar_rota_no_historico("Campinas", "Belém, Pará, Brasil", None) is None
    assert geo._buscar_rota_no_historico("Campinas", "Belém, Pará, Brasil", "") is None


def test_usa_a_cotacao_mais_recente_quando_ha_varias(banco_temporario):
    _salvar_rota("Campinas", "Belém, Pará, Brasil", 2900, veiculo="VUC")  # mais antiga
    _salvar_rota("Campinas", "Belém, Pará, Brasil", 2950, veiculo="VUC")  # mais recente (salva depois)
    achado = geo._buscar_rota_no_historico("Campinas", "Belém, Pará, Brasil", "VUC")
    assert achado["distancia_km"] == 2950


def test_buscar_rota_no_historico_none_quando_origem_ou_destino_atual_nao_identificavel(banco_temporario):
    _salvar_rota("Campinas", "Belém, Pará, Brasil", 2900, veiculo="VUC")
    assert geo._buscar_rota_no_historico(" , , ", "Belém, Pará, Brasil", "VUC") is None


def test_buscar_rota_no_historico_ignora_linha_salva_com_origem_ou_destino_vazio(banco_temporario):
    # registro antigo/malformado (origem_resumo ou destino_resumo em
    # branco) não pode quebrar a busca -- só é ignorado, segue pras
    # próximas linhas.
    _salvar_rota("", "", 2900, veiculo="VUC")
    _salvar_rota("Campinas", "Belém, Pará, Brasil", 3000, veiculo="VUC")
    achado = geo._buscar_rota_no_historico("Campinas", "Belém, Pará, Brasil", "VUC")
    assert achado is not None
    assert achado["distancia_km"] == 3000


def test_calcular_distancia_nao_chama_servico_externo_quando_ja_no_historico(banco_temporario, monkeypatch):
    _salvar_rota("Campinas", "Belém, Pará, Brasil", 2900, veiculo="VUC")

    async def _geocode_nao_deveria_ser_chamado(*a, **k):
        raise AssertionError("não deveria geocodificar: rota já estava no histórico")

    monkeypatch.setattr(geo, "_geocode", _geocode_nao_deveria_ser_chamado)

    resultado = asyncio.run(geo.calcular_distancia("Campinas", "Belém, Pará, Brasil", veiculo="VUC"))
    assert resultado["distancia_km"] == 2900
    assert resultado["duracao_min"] > 0
    assert resultado["origem_resolvido"] == "Campinas"
    assert resultado["destino_resolvido"] == "Belém, Pará, Brasil"


def test_calcular_distancia_sem_veiculo_geocodifica_normalmente(banco_temporario, monkeypatch):
    _salvar_rota("Campinas", "Belém, Pará, Brasil", 2900, veiculo="VUC")

    chamou_geocode = []

    async def _geocode_fake(client, endereco, dica_cidade=None):
        chamou_geocode.append(endereco)
        return (0.0, 0.0, endereco)

    async def _rota_fake(client, lat1, lon1, lat2, lon2):
        return {"distancia_km": 123, "duracao_min": 99, "pedagio_valor": None, "pedagio_moeda": None}

    monkeypatch.setattr(geo, "_geocode", _geocode_fake)
    monkeypatch.setattr(geo, "_rota", _rota_fake)

    resultado = asyncio.run(geo.calcular_distancia("Campinas", "Belém, Pará, Brasil"))
    assert resultado["distancia_km"] == 123
    assert len(chamou_geocode) == 2  # geocodificou os dois endereços de verdade


def test_calcular_distancia_com_prioridade_rota_soma_as_duas_pernas(banco_temporario, monkeypatch):
    # Destino Manaus não tem acesso rodoviário direto -- uma prioridade de
    # rota "*" -> "Manaus" via Belém precisa fazer a distância final ser a
    # soma origem->Belém + Belém->Manaus, não a rota direta.
    p = fs.ParametrosFrete()
    p.filiais = {"belém": fs.Filial("Belém", "Centro, Belém, PA, Brasil", None, None)}
    p.prioridades_rota = [
        fs.PrioridadeRota(estado_origem="*", cidade_destino="Manaus", filial_escala="Belém"),
    ]
    monkeypatch.setattr(fs, "parametros", p)

    async def _geocode_fake(client, endereco, dica_cidade=None):
        resolvidos = {
            "São Paulo": (0.0, 0.0, "Rua X, São Paulo, São Paulo, Brasil"),
            "Manaus": (0.0, 0.0, "Rua Y, Manaus, Amazonas, Brasil"),
        }
        return resolvidos[endereco]

    async def _coordenadas_filial_fake(client, filial):
        return (1.0, 1.0)

    chamadas_rota = []

    async def _rota_fake(client, lat1, lon1, lat2, lon2):
        chamadas_rota.append((lat1, lon1, lat2, lon2))
        if len(chamadas_rota) == 1:
            return {"distancia_km": 2500, "duracao_min": 1800, "pedagio_valor": 50.0, "pedagio_moeda": "BRL"}
        return {"distancia_km": 400, "duracao_min": 300, "pedagio_valor": None, "pedagio_moeda": None}

    monkeypatch.setattr(geo, "_geocode", _geocode_fake)
    monkeypatch.setattr(geo, "coordenadas_filial", _coordenadas_filial_fake)
    monkeypatch.setattr(geo, "_rota", _rota_fake)

    resultado = asyncio.run(geo.calcular_distancia("São Paulo", "Manaus"))
    assert resultado["distancia_km"] == 2900  # 2500 + 400
    assert resultado["duracao_min"] == 2100  # 1800 + 300
    assert resultado["pedagio_valor"] == pytest.approx(50.0)
    assert resultado["prioridade_rota"] == "Belém"
    assert len(chamadas_rota) == 2  # uma perna pra cada trecho, nunca a rota direta


def test_calcular_distancia_sem_prioridade_rota_faz_rota_direta(banco_temporario, monkeypatch):
    p = fs.ParametrosFrete()
    p.filiais = {}
    p.prioridades_rota = []
    monkeypatch.setattr(fs, "parametros", p)

    async def _geocode_fake(client, endereco, dica_cidade=None):
        return (0.0, 0.0, endereco)

    chamadas_rota = []

    async def _rota_fake(client, lat1, lon1, lat2, lon2):
        chamadas_rota.append((lat1, lon1, lat2, lon2))
        return {"distancia_km": 300, "duracao_min": 200, "pedagio_valor": None, "pedagio_moeda": None}

    monkeypatch.setattr(geo, "_geocode", _geocode_fake)
    monkeypatch.setattr(geo, "_rota", _rota_fake)

    resultado = asyncio.run(geo.calcular_distancia("Campinas", "Curitiba, PR, Brasil"))
    assert resultado["distancia_km"] == 300
    assert "prioridade_rota" not in resultado
    assert len(chamadas_rota) == 1  # rota direta, sem dividir em pernas


def _parametros_com_pedagio_local():
    p = fs.ParametrosFrete()
    p.filiais = {}
    p.prioridades_rota = []
    p.veiculos = {
        "vuc": fs.Veiculo(
            nome="VUC", de=0, ate=1000, tarifa_km=2.0, valor_tonelada_excedente=1.0, numero_eixos=2,
        ),
    }
    p.pracas_pedagio = {1: fs.PracaPedagio(1, "Praça 5", "BR-101", "ViaSul", {2: 42.0})}
    p.pedagios_rota = [fs.PedagioRota("Curitiba", "Florianópolis", 1)]
    return p


def test_calcular_distancia_usa_pedagio_local_quando_corredor_cadastrado(banco_temporario, monkeypatch):
    # Corredor cadastrado (ver frete_service.pedagio_rota_aplicavel) tem
    # prioridade sobre a estimativa genérica do Google/OSRM, por ser mais
    # precisa (sabe a praça/concessionária real).
    monkeypatch.setattr(fs, "parametros", _parametros_com_pedagio_local())

    async def _geocode_fake(client, endereco, dica_cidade=None):
        resolvidos = {
            "Curitiba": (0.0, 0.0, "Curitiba, PR, Brasil"),
            "Florianópolis": (0.0, 0.0, "Florianópolis, SC, Brasil"),
        }
        return resolvidos[endereco]

    async def _rota_fake(client, lat1, lon1, lat2, lon2):
        return {"distancia_km": 300, "duracao_min": 200, "pedagio_valor": 99.0, "pedagio_moeda": "USD"}

    monkeypatch.setattr(geo, "_geocode", _geocode_fake)
    monkeypatch.setattr(geo, "_rota", _rota_fake)

    resultado = asyncio.run(geo.calcular_distancia("Curitiba", "Florianópolis", veiculo="VUC"))
    assert resultado["pedagio_valor"] == pytest.approx(42.0)
    assert resultado["pedagio_moeda"] == "BRL"
    assert resultado["pedagio_pracas"] == ["Praça 5"]


def test_calcular_distancia_sem_corredor_mantem_estimativa_do_provedor(banco_temporario, monkeypatch):
    monkeypatch.setattr(fs, "parametros", _parametros_com_pedagio_local())

    async def _geocode_fake(client, endereco, dica_cidade=None):
        return (0.0, 0.0, endereco)

    async def _rota_fake(client, lat1, lon1, lat2, lon2):
        return {"distancia_km": 300, "duracao_min": 200, "pedagio_valor": 99.0, "pedagio_moeda": "USD"}

    monkeypatch.setattr(geo, "_geocode", _geocode_fake)
    monkeypatch.setattr(geo, "_rota", _rota_fake)

    # rota diferente da cadastrada (Curitiba -> Florianópolis) -- não bate
    # nenhum corredor, mantém o que o provedor de rota devolveu
    resultado = asyncio.run(geo.calcular_distancia("Campinas", "Curitiba, PR, Brasil", veiculo="VUC"))
    assert resultado["pedagio_valor"] == pytest.approx(99.0)
    assert resultado["pedagio_moeda"] == "USD"
    assert resultado["pedagio_pracas"] == []


def test_calcular_distancia_reaproveitada_do_historico_tambem_usa_pedagio_local(banco_temporario, monkeypatch):
    monkeypatch.setattr(fs, "parametros", _parametros_com_pedagio_local())
    _salvar_rota("Curitiba", "Florianópolis", 300, veiculo="VUC")

    resultado = asyncio.run(geo.calcular_distancia("Curitiba", "Florianópolis", veiculo="VUC"))
    assert resultado["distancia_km"] == 300
    assert resultado["pedagio_valor"] == pytest.approx(42.0)
    assert resultado["pedagio_moeda"] == "BRL"
    assert resultado["pedagio_pracas"] == ["Praça 5"]


def test_nao_reaproveita_historico_quando_ha_distancia_fixa_cadastrada(banco_temporario, monkeypatch):
    # Cenário real: um orçamento Belém->Manaus foi cotado e salvo ANTES de
    # existir a distância fixa (balsa) cadastrada pra essa rota -- guardou
    # a rota terrestre real (3031 km, via BR-319). Depois, alguém cadastra
    # a distância fixa correta (2096 km, balsa). Reaproveitar o histórico
    # às cegas manteria a rota terrestre errada pra sempre nas cotações
    # seguintes -- por isso não pode reaproveitar quando há distância fixa
    # cadastrada pro par de cidades, mesmo que o histórico bata.
    _salvar_rota("Belém", "Manaus", 3031, veiculo="Carreta")

    p = fs.ParametrosFrete()
    p.filiais = {}
    p.prioridades_rota = []
    p.distancias_fixas = [fs.DistanciaFixa("Belém", "Manaus", 2096)]
    monkeypatch.setattr(fs, "parametros", p)

    assert geo._buscar_rota_no_historico("Belém", "Manaus", "Carreta") is None


def test_nao_reaproveita_historico_quando_ha_prioridade_rota_cadastrada(banco_temporario, monkeypatch):
    # Mesma ideia, mas pro caso de uma rota completa (ex: Campinas->Manaus)
    # cotada antes de existir a Prioridade de Rota (escala obrigatória por
    # Belém) cadastrada pro destino Manaus.
    _salvar_rota("Campinas", "Manaus", 5810, veiculo="Carreta")

    p = fs.ParametrosFrete()
    p.filiais = {"belém": fs.Filial("Belém", "Centro, Belém, PA, Brasil", None, None)}
    p.prioridades_rota = [fs.PrioridadeRota(estado_origem="*", cidade_destino="Manaus", filial_escala="Belém")]
    p.distancias_fixas = []
    monkeypatch.setattr(fs, "parametros", p)

    assert geo._buscar_rota_no_historico("Campinas", "Manaus", "Carreta") is None


def test_calcular_distancia_usa_distancia_fixa_na_rota_direta(banco_temporario, monkeypatch):
    # Distância fixa cadastrada (ver frete_service.distancia_fixa_aplicavel)
    # sobrepõe o cálculo rodoviário de verdade -- útil quando a rota real
    # usada na prática (ex: com balsa) é bem diferente da rota puramente
    # rodoviária que o serviço de mapa calcularia.
    p = fs.ParametrosFrete()
    p.filiais = {}
    p.prioridades_rota = []
    p.distancias_fixas = [fs.DistanciaFixa("Belém", "Manaus", 2096)]
    monkeypatch.setattr(fs, "parametros", p)

    async def _geocode_fake(client, endereco, dica_cidade=None):
        resolvidos = {
            "Belem": (0.0, 0.0, "Belém, Pará, Brasil"),
            "Manaus": (0.0, 0.0, "Manaus, Amazonas, Brasil"),
        }
        return resolvidos[endereco]

    chamou_rota_de_verdade = []

    async def _rota_fake(client, lat1, lon1, lat2, lon2):
        chamou_rota_de_verdade.append(True)
        return {"distancia_km": 3035, "duracao_min": 3409, "pedagio_valor": None, "pedagio_moeda": None}

    monkeypatch.setattr(geo, "_geocode", _geocode_fake)
    monkeypatch.setattr(geo, "_rota", _rota_fake)

    resultado = asyncio.run(geo.calcular_distancia("Belem", "Manaus"))
    assert resultado["distancia_km"] == 2096
    assert chamou_rota_de_verdade == []  # não precisou chamar o serviço de rota de verdade


def test_calcular_distancia_usa_distancia_fixa_numa_perna_da_prioridade_de_rota(banco_temporario, monkeypatch):
    # A distância fixa também vale dentro de cada perna de uma escala
    # obrigatória (Prioridade de Rota) -- ex: origem -> Belém continua
    # sendo calculada de verdade, mas Belém -> Manaus usa o valor fixo.
    p = fs.ParametrosFrete()
    p.filiais = {"belém": fs.Filial("Belém", "Centro, Belém, PA, Brasil", None, None)}
    p.prioridades_rota = [fs.PrioridadeRota(estado_origem="*", cidade_destino="Manaus", filial_escala="Belém")]
    p.distancias_fixas = [fs.DistanciaFixa("Belém", "Manaus", 2096)]
    monkeypatch.setattr(fs, "parametros", p)

    async def _geocode_fake(client, endereco, dica_cidade=None):
        resolvidos = {
            "São Paulo": (0.0, 0.0, "São Paulo, São Paulo, Brasil"),
            "Manaus": (0.0, 0.0, "Manaus, Amazonas, Brasil"),
        }
        return resolvidos[endereco]

    async def _coordenadas_filial_fake(client, filial):
        return (1.0, 1.0)

    chamadas_rota_de_verdade = []

    async def _rota_fake(client, lat1, lon1, lat2, lon2):
        chamadas_rota_de_verdade.append((lat1, lon1, lat2, lon2))
        return {"distancia_km": 2849, "duracao_min": 2000, "pedagio_valor": None, "pedagio_moeda": None}

    monkeypatch.setattr(geo, "_geocode", _geocode_fake)
    monkeypatch.setattr(geo, "coordenadas_filial", _coordenadas_filial_fake)
    monkeypatch.setattr(geo, "_rota", _rota_fake)

    resultado = asyncio.run(geo.calcular_distancia("São Paulo", "Manaus"))
    # perna 1 (São Paulo -> Belém) veio do "_rota" de verdade (2849);
    # perna 2 (Belém -> Manaus) veio da distância fixa (2096), não da rota_fake
    assert resultado["distancia_km"] == 2849 + 2096
    assert len(chamadas_rota_de_verdade) == 1  # só a perna 1 chamou o serviço de rota


def test_calcular_distancia_prioridade_rota_com_filial_escala_inexistente_da_erro(banco_temporario, monkeypatch):
    # Prioridade de rota cadastrada aponta pra uma filial que foi excluída
    # (ou nunca existiu) -- precisa de um erro claro, não travar/quebrar.
    p = fs.ParametrosFrete()
    p.filiais = {}  # "Belém" não está cadastrada
    p.prioridades_rota = [fs.PrioridadeRota(estado_origem="*", cidade_destino="Manaus", filial_escala="Belém")]
    monkeypatch.setattr(fs, "parametros", p)

    async def _geocode_fake(client, endereco, dica_cidade=None):
        resolvidos = {
            "São Paulo": (0.0, 0.0, "São Paulo, São Paulo, Brasil"),
            "Manaus": (0.0, 0.0, "Manaus, Amazonas, Brasil"),
        }
        return resolvidos[endereco]

    monkeypatch.setattr(geo, "_geocode", _geocode_fake)

    with pytest.raises(geo.GeoError, match="Belém"):
        asyncio.run(geo.calcular_distancia("São Paulo", "Manaus"))


def test_calcular_distancia_prioridade_rota_tambem_usa_pedagio_local(banco_temporario, monkeypatch):
    # Mesmo raciocínio de test_calcular_distancia_usa_pedagio_local_quando_corredor_cadastrado
    # (mais abaixo), mas dentro do ramo de Prioridade de Rota -- o
    # corredor cadastrado é pela rota completa (origem->destino), não por
    # perna da escala.
    p = _parametros_com_pedagio_local()
    p.filiais = {"belém": fs.Filial("Belém", "Centro, Belém, PA, Brasil", None, None)}
    p.prioridades_rota = [fs.PrioridadeRota(estado_origem="*", cidade_destino="Florianópolis", filial_escala="Belém")]
    monkeypatch.setattr(fs, "parametros", p)

    async def _geocode_fake(client, endereco, dica_cidade=None):
        resolvidos = {
            "Curitiba": (0.0, 0.0, "Curitiba, PR, Brasil"),
            "Florianópolis": (0.0, 0.0, "Florianópolis, SC, Brasil"),
        }
        return resolvidos[endereco]

    async def _coordenadas_filial_fake(client, filial):
        return (1.0, 1.0)

    async def _rota_fake(client, lat1, lon1, lat2, lon2):
        return {"distancia_km": 300, "duracao_min": 200, "pedagio_valor": 99.0, "pedagio_moeda": "USD"}

    monkeypatch.setattr(geo, "_geocode", _geocode_fake)
    monkeypatch.setattr(geo, "coordenadas_filial", _coordenadas_filial_fake)
    monkeypatch.setattr(geo, "_rota", _rota_fake)

    resultado = asyncio.run(geo.calcular_distancia("Curitiba", "Florianópolis", veiculo="VUC"))
    assert resultado["pedagio_valor"] == pytest.approx(42.0)  # veio do corredor cadastrado, não da _rota_fake (99.0)
    assert resultado["pedagio_moeda"] == "BRL"


# ============================================================
# coordenadas_filial
# ============================================================


def test_coordenadas_filial_usa_cache_quando_ja_geocodificada():
    filial = fs.Filial("SP", "Endereço Teste", -23.5, -46.6)
    resultado = asyncio.run(geo.coordenadas_filial(None, filial))  # client nem chega a ser usado
    assert resultado == (-23.5, -46.6)


def test_coordenadas_filial_geocodifica_e_persiste_quando_ausente(banco_temporario, monkeypatch):
    db.inserir_filial("Filial Teste Coordenadas", "Rua X, 100, Campinas, SP", uf="SP")
    filial = fs.Filial("Filial Teste Coordenadas", "Rua X, 100, Campinas, SP", None, None)

    async def _geocode_fake(client, endereco, dica_cidade=None):
        assert dica_cidade == "Filial Teste Coordenadas"  # usa o nome da filial como dica de cidade
        return (-22.9, -47.1, "Rua X, 100, Campinas, SP, Brasil")

    monkeypatch.setattr(geo, "_geocode", _geocode_fake)
    lat, lon = asyncio.run(geo.coordenadas_filial(None, filial))
    assert (lat, lon) == (-22.9, -47.1)
    assert filial.latitude == -22.9  # objeto em memória também atualizado
    assert filial.longitude == -47.1

    # persistiu no banco -- uma próxima leitura já vem com coordenada
    salva = [f for f in db.listar_filiais_admin() if f["nome"] == "Filial Teste Coordenadas"][0]
    assert salva["latitude"] == pytest.approx(-22.9)
    assert salva["longitude"] == pytest.approx(-47.1)


# ============================================================
# calcular_distancia -- validação de entrada
# ============================================================


def test_calcular_distancia_sem_origem_da_erro():
    with pytest.raises(geo.GeoError, match="origem"):
        asyncio.run(geo.calcular_distancia("", "Curitiba, PR, Brasil"))
    with pytest.raises(geo.GeoError, match="origem"):
        asyncio.run(geo.calcular_distancia("   ", "Curitiba, PR, Brasil"))


def test_calcular_distancia_sem_destino_da_erro():
    with pytest.raises(geo.GeoError, match="destino"):
        asyncio.run(geo.calcular_distancia("Campinas, SP", ""))


# ============================================================
# usando_google / cache de geocodificação
# ============================================================


def test_usando_google_falso_por_padrao():
    assert geo.usando_google() is False


def test_usando_google_verdadeiro_com_chave_configurada(monkeypatch):
    monkeypatch.setattr(geo, "GOOGLE_MAPS_API_KEY", "chave-de-teste")
    assert geo.usando_google() is True


def test_geocode_cache_get_set_e_lru():
    geo._geocode_cache.clear()
    assert geo._geocode_cache_get("campinas, sp") is None

    geo._geocode_cache_set("campinas, sp", (1.0, 2.0, "Campinas, SP, Brasil"))
    assert geo._geocode_cache_get("campinas, sp") == (1.0, 2.0, "Campinas, SP, Brasil")


def test_geocode_cache_descarta_o_mais_antigo_quando_cheio(monkeypatch):
    geo._geocode_cache.clear()
    monkeypatch.setattr(geo, "_GEOCODE_CACHE_MAX", 2)

    geo._geocode_cache_set("a", (0.0, 0.0, "A"))
    geo._geocode_cache_set("b", (0.0, 0.0, "B"))
    geo._geocode_cache_set("c", (0.0, 0.0, "C"))  # estoura o limite -> descarta "a" (o mais antigo)

    assert geo._geocode_cache_get("a") is None
    assert geo._geocode_cache_get("b") is not None
    assert geo._geocode_cache_get("c") is not None


# ============================================================
# _extrair_cep
# ============================================================


@pytest.mark.parametrize("endereco,esperado", [
    ("Rua X, 100, CEP: 13.054-740, Campinas, SP", "13054-740"),
    ("Rua X, 100, 13054740, Campinas, SP", "13054-740"),
    ("Rua X, 100, Campinas, SP", None),
])
def test_extrair_cep(endereco, esperado):
    assert geo._extrair_cep(endereco) == esperado


# ============================================================
# _variantes_endereco
# ============================================================


def test_variantes_endereco_sempre_inclui_o_original():
    assert "Rua X, 100, Campinas, SP" in geo._variantes_endereco("Rua X, 100, Campinas, SP")


def test_variantes_endereco_remove_parenteses():
    variantes = geo._variantes_endereco("Rua X, 100 (Zona Sul), Campinas, SP")
    assert any("Zona Sul" not in v and "(" not in v for v in variantes)


def test_variantes_endereco_remove_segmento_de_cep():
    variantes = geo._variantes_endereco("Rua X, 100, CEP: 13054-740, Campinas, SP")
    # pelo menos uma variante não deve mais citar o rótulo "CEP"
    assert any("cep" not in v.lower() for v in variantes)


def test_variantes_endereco_remove_rotulo_bairro():
    variantes = geo._variantes_endereco("Rua X, 100, bairro Distrito Industrial, Campinas, SP")
    assert any("bairro" not in v.lower() for v in variantes)


def test_variantes_endereco_rua_mais_ultimo_segmento_quando_tem_mais_de_2_partes():
    # remove o miolo (número, complemento, bairro), fica só primeiro
    # segmento + último -- não "rua + cidade", literalmente o último
    # segmento do endereço (aqui, a UF).
    variantes = geo._variantes_endereco("Rua X, 100, sala 5, Distrito Industrial, Campinas, SP")
    assert "Rua X, SP" in variantes


def test_variantes_endereco_remove_qualificador_de_unidade():
    variantes = geo._variantes_endereco("Rodovia BR 316, Km 05, Bloco A, Belém, PA")
    # a rua limpa (sem "Km 05" nem "Bloco A") deve aparecer em alguma variante
    assert any("Km 05" not in v and "Bloco A" not in v for v in variantes)


def test_variantes_endereco_remove_qualificador_no_meio_do_primeiro_segmento():
    # qualificador colado no fim do primeiro segmento (não isolado numa
    # vírgula própria, como no teste acima) -- ainda assim precisa sumir
    # numa variante própria (rua limpa + último segmento).
    variantes = geo._variantes_endereco("Rua Exemplo Bloco B, Belém, PA")
    assert "Rua Exemplo, PA" in variantes
    assert "Rua Exemplo" in variantes


def test_variantes_endereco_qualificador_em_endereco_de_um_segmento_so():
    # endereço sem vírgula nenhuma (1 segmento só) -- cai no ramo "elif"
    # (len(partes_sem_cep) < 2), não no "if" usado pelos testes acima.
    variantes = geo._variantes_endereco("Sala 5 Rua Exemplo")
    assert "Rua Exemplo" in variantes


def test_variantes_endereco_acrescenta_dica_de_cidade_quando_ausente():
    variantes = geo._variantes_endereco("Rua X, 100", dica_cidade="Campinas")
    assert any("Campinas" in v for v in variantes)


def test_variantes_endereco_nao_duplica_dica_de_cidade_ja_presente():
    variantes = geo._variantes_endereco("Rua X, 100, Campinas, SP", dica_cidade="Campinas")
    # não deve ter nenhuma variante repetida (case-insensitive)
    assert len(variantes) == len({v.strip().lower() for v in variantes})


def test_variantes_endereco_sem_duplicatas():
    variantes = geo._variantes_endereco("Rua X, 100, Campinas, SP, Brasil")
    assert len(variantes) == len(set(v.lower() for v in variantes))


# ============================================================
# _haversine_km
# ============================================================


def test_haversine_km_mesmo_ponto_e_zero():
    assert geo._haversine_km(-22.9, -47.1, -22.9, -47.1) == pytest.approx(0.0)


def test_haversine_km_distancia_conhecida_sp_rj():
    # São Paulo -> Rio de Janeiro em linha reta é ~360km (valor de referência,
    # tolerância generosa só pra pegar erro grosseiro de fórmula/unidade).
    distancia = geo._haversine_km(-23.5505, -46.6333, -22.9068, -43.1729)
    assert 340 < distancia < 380


# ============================================================
# resolver_retirada (nível de geo_service, não do router)
# ============================================================


def _filial_fake(nome, lat, lon):
    return fs.Filial(nome, f"Endereço de {nome}", lat, lon)


def test_resolver_retirada_sem_endereco_da_erro():
    with pytest.raises(geo.GeoError, match="retirada"):
        asyncio.run(geo.resolver_retirada("", [_filial_fake("SP", -23.5, -46.6)]))


def test_resolver_retirada_sem_filiais_cadastradas_da_erro():
    with pytest.raises(geo.GeoError, match="filial"):
        asyncio.run(geo.resolver_retirada("Rua X, 100, Campinas, SP", []))


def test_resolver_retirada_escolhe_a_filial_mais_proxima(monkeypatch):
    filiais = [
        _filial_fake("São Paulo", -23.5505, -46.6333),
        _filial_fake("Campinas", -22.9099, -47.0626),  # mais perto do endereço de teste
    ]

    async def _geocode_fake(client, endereco, dica_cidade=None):
        return (-22.90, -47.05, "Rua X, 100, Campinas, SP, Brasil")  # perto de Campinas

    async def _coordenadas_filial_fake(client, filial):
        return filial.latitude, filial.longitude

    chamou_rota_com = []

    async def _rota_fake(client, lat1, lon1, lat2, lon2):
        chamou_rota_com.append((lat1, lon1, lat2, lon2))
        return {"distancia_km": 12, "duracao_min": 20, "pedagio_valor": None, "pedagio_moeda": None}

    monkeypatch.setattr(geo, "_geocode", _geocode_fake)
    monkeypatch.setattr(geo, "coordenadas_filial", _coordenadas_filial_fake)
    monkeypatch.setattr(geo, "_rota", _rota_fake)

    resultado = asyncio.run(geo.resolver_retirada("Rua X, 100, Campinas, SP", filiais))
    assert resultado["filial_mais_proxima"] == "Campinas"
    assert resultado["distancia_coleta_km"] == 12
    assert resultado["duracao_coleta_min"] == 20
    # a rota real só é calculada pra filial vencedora (Campinas), não pras duas
    assert len(chamou_rota_com) == 1
    assert chamou_rota_com[0] == (-22.9099, -47.0626, -22.90, -47.05)


# ============================================================
# _rota -- escolhe OSRM ou Google conforme usando_google()
# ============================================================


def test_rota_usa_osrm_por_padrao(monkeypatch):
    chamou = []

    async def _osrm_fake(client, lat1, lon1, lat2, lon2):
        chamou.append("osrm")
        return {"distancia_km": 1, "duracao_min": 1, "pedagio_valor": None, "pedagio_moeda": None}

    async def _google_fake(client, lat1, lon1, lat2, lon2):
        chamou.append("google")
        return {"distancia_km": 1, "duracao_min": 1, "pedagio_valor": None, "pedagio_moeda": None}

    monkeypatch.setattr(geo, "_rota_osrm", _osrm_fake)
    monkeypatch.setattr(geo, "_rota_google", _google_fake)

    asyncio.run(geo._rota(None, 0, 0, 0, 0))
    assert chamou == ["osrm"]


def test_rota_usa_google_quando_configurado(monkeypatch):
    monkeypatch.setattr(geo, "GOOGLE_MAPS_API_KEY", "chave-de-teste")
    chamou = []

    async def _osrm_fake(client, lat1, lon1, lat2, lon2):
        chamou.append("osrm")
        return {"distancia_km": 1, "duracao_min": 1, "pedagio_valor": None, "pedagio_moeda": None}

    async def _google_fake(client, lat1, lon1, lat2, lon2):
        chamou.append("google")
        return {"distancia_km": 1, "duracao_min": 1, "pedagio_valor": None, "pedagio_moeda": None}

    monkeypatch.setattr(geo, "_rota_osrm", _osrm_fake)
    monkeypatch.setattr(geo, "_rota_google", _google_fake)

    asyncio.run(geo._rota(None, 0, 0, 0, 0))
    assert chamou == ["google"]


# ============================================================
# Funções de baixo nível que chamam o serviço externo de verdade
# (Nominatim/OSRM/Google) -- mocadas com um httpx.AsyncClient fake, sem
# nenhuma chamada de rede real.
# ============================================================


class _RespostaFake:
    def __init__(self, dados, status_code=200):
        self._dados = dados
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "http://teste")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("erro de status", request=request, response=response)

    def json(self):
        return self._dados


class _ClienteFake:
    """Confunde httpx.AsyncClient o suficiente pras funções de
    _tentar_busca/_geocode_google/_rota_osrm/_rota_google (só usam
    .get/.post) -- devolve sempre a mesma resposta fake, ou levanta o
    erro de conexão configurado."""

    def __init__(self, resposta=None, erro_conexao=None):
        self._resposta = resposta
        self._erro_conexao = erro_conexao

    async def get(self, *args, **kwargs):
        if self._erro_conexao:
            raise self._erro_conexao
        return self._resposta

    async def post(self, *args, **kwargs):
        if self._erro_conexao:
            raise self._erro_conexao
        return self._resposta


def test_geocode_nominatim_sucesso():
    resposta = _RespostaFake([{"lat": "-22.9", "lon": "-47.1", "display_name": "Campinas, SP, Brasil"}])
    resultado = asyncio.run(geo._geocode_nominatim(_ClienteFake(resposta), {"q": "Campinas"}))
    assert resultado == (-22.9, -47.1, "Campinas, SP, Brasil")


def test_geocode_nominatim_sem_resultado():
    resposta = _RespostaFake([])
    resultado = asyncio.run(geo._geocode_nominatim(_ClienteFake(resposta), {"q": "endereço inexistente"}))
    assert resultado is None


def test_geocode_google_sucesso():
    dados = {
        "status": "OK",
        "results": [{
            "geometry": {"location": {"lat": -22.9, "lng": -47.1}},
            "formatted_address": "Campinas, SP, Brasil",
        }],
    }
    resultado = asyncio.run(geo._geocode_google(_ClienteFake(_RespostaFake(dados)), "Campinas"))
    assert resultado == (-22.9, -47.1, "Campinas, SP, Brasil")


def test_geocode_google_zero_results():
    dados = {"status": "ZERO_RESULTS", "results": []}
    resultado = asyncio.run(geo._geocode_google(_ClienteFake(_RespostaFake(dados)), "endereço inexistente"))
    assert resultado is None


def test_geocode_google_erro_de_configuracao():
    dados = {"status": "REQUEST_DENIED", "results": []}
    with pytest.raises(geo.GeoError, match="Google Maps"):
        asyncio.run(geo._geocode_google(_ClienteFake(_RespostaFake(dados)), "Campinas"))


def test_geocode_erro_de_conexao_tenta_variantes_e_por_fim_desiste(monkeypatch):
    # todas as tentativas falham por erro de conexão (não por endereço não
    # encontrado) -- o erro final reportado precisa ser o de conexão, não
    # o genérico de "endereço não encontrado".
    monkeypatch.setattr(geo, "_variantes_endereco", lambda endereco, dica_cidade=None: [endereco])
    geo._geocode_cache.clear()

    cliente = _ClienteFake(erro_conexao=httpx.ConnectError("falha de rede"))
    with pytest.raises(geo.GeoError, match="Falha ao consultar"):
        asyncio.run(geo._geocode(cliente, "Rua Inacessível, 1"))


def test_geocode_usa_cache_quando_ja_tem_endereco_geocodificado():
    geo._geocode_cache.clear()
    geo._geocode_cache_set("rua já geocodificada, 1", (-22.9, -47.1, "Rua Já Geocodificada, 1, Brasil"))
    # client=None -- se caísse pra rede de verdade, quebraria aqui
    resultado = asyncio.run(geo._geocode(None, "Rua Já Geocodificada, 1"))
    assert resultado == (-22.9, -47.1, "Rua Já Geocodificada, 1, Brasil")


def test_geocode_branch_google_sucesso_na_primeira_variante(monkeypatch):
    monkeypatch.setattr(geo, "GOOGLE_MAPS_API_KEY", "chave-de-teste")
    monkeypatch.setattr(geo, "_variantes_endereco", lambda endereco, dica_cidade=None: [endereco])
    geo._geocode_cache.clear()

    dados = {
        "status": "OK",
        "results": [{
            "geometry": {"location": {"lat": -22.9, "lng": -47.1}},
            "formatted_address": "Campinas, SP, Brasil",
        }],
    }
    cliente = _ClienteFake(_RespostaFake(dados))
    resultado = asyncio.run(geo._geocode(cliente, "Campinas"))
    assert resultado == (-22.9, -47.1, "Campinas, SP, Brasil")
    assert geo._geocode_cache_get("campinas") == (-22.9, -47.1, "Campinas, SP, Brasil")


def test_geocode_branch_google_erro_de_configuracao_interrompe_tentativas(monkeypatch):
    # REQUEST_DENIED (chave inválida) não deve continuar tentando as
    # demais variações do endereço -- é um erro de configuração, não de
    # endereço mal formatado.
    monkeypatch.setattr(geo, "GOOGLE_MAPS_API_KEY", "chave-invalida")
    monkeypatch.setattr(
        geo, "_variantes_endereco", lambda endereco, dica_cidade=None: [endereco, "variante 2"]
    )
    geo._geocode_cache.clear()

    chamadas = []

    async def _geocode_google_fake(client, texto):
        chamadas.append(texto)
        raise geo.GeoError("Google Maps recusou a consulta de geocodificação (status: REQUEST_DENIED).")

    monkeypatch.setattr(geo, "_geocode_google", _geocode_google_fake)

    with pytest.raises(geo.GeoError, match="REQUEST_DENIED"):
        asyncio.run(geo._geocode(_ClienteFake(), "Rua Exemplo"))
    assert chamadas == ["Rua Exemplo"]  # parou na primeira, não tentou "variante 2"


def test_geocode_branch_nominatim_usa_cep_como_busca_estruturada(monkeypatch):
    # Quando o endereço tem CEP e as variações de texto livre não encontram
    # nada, tenta uma busca estruturada só pelo CEP como último recurso.
    monkeypatch.setattr(geo, "GOOGLE_MAPS_API_KEY", "")
    monkeypatch.setattr(geo, "_variantes_endereco", lambda endereco, dica_cidade=None: ["Rua Exemplo, 100"])
    geo._geocode_cache.clear()

    chamadas_params = []

    async def _geocode_nominatim_fake(client, params):
        chamadas_params.append(params)
        if "postalcode" in params:
            return (-22.9, -47.1, "Rua Exemplo, 100, Campinas, SP, 13000-000, Brasil")
        return None

    monkeypatch.setattr(geo, "_geocode_nominatim", _geocode_nominatim_fake)

    resultado = asyncio.run(geo._geocode(_ClienteFake(), "Rua Exemplo, 100, CEP 13000-000"))
    assert resultado[2] == "Rua Exemplo, 100, Campinas, SP, 13000-000, Brasil"
    assert chamadas_params[-1] == {"postalcode": "13000-000", "country": "Brazil"}


def test_geocode_endereco_nao_encontrado_gera_erro_generico(monkeypatch):
    monkeypatch.setattr(geo, "GOOGLE_MAPS_API_KEY", "")
    monkeypatch.setattr(geo, "_variantes_endereco", lambda endereco, dica_cidade=None: [endereco])
    geo._geocode_cache.clear()

    async def _geocode_nominatim_fake(client, params):
        return None

    monkeypatch.setattr(geo, "_geocode_nominatim", _geocode_nominatim_fake)

    with pytest.raises(geo.GeoError, match="Endereço não encontrado"):
        asyncio.run(geo._geocode(_ClienteFake(), "Rua Que Não Existe Em Lugar Nenhum, 999999"))


def test_rota_osrm_sucesso():
    dados = {"code": "Ok", "routes": [{"distance": 12345, "duration": 600}]}
    resultado = asyncio.run(geo._rota_osrm(_ClienteFake(_RespostaFake(dados)), -22.9, -47.1, -23.5, -46.6))
    assert resultado["distancia_km"] == 12  # 12345m arredondado pra km
    assert resultado["duracao_min"] == 10  # 600s = 10min
    assert resultado["pedagio_valor"] is None


def test_rota_osrm_sem_rota_encontrada():
    dados = {"code": "NoRoute", "routes": []}
    with pytest.raises(geo.GeoError, match="rota rodoviária"):
        asyncio.run(geo._rota_osrm(_ClienteFake(_RespostaFake(dados)), -22.9, -47.1, -23.5, -46.6))


def test_rota_osrm_erro_de_conexao():
    cliente = _ClienteFake(erro_conexao=httpx.ConnectError("falha de rede"))
    with pytest.raises(geo.GeoError, match="Falha ao calcular"):
        asyncio.run(geo._rota_osrm(cliente, -22.9, -47.1, -23.5, -46.6))


def test_rota_google_sucesso_com_pedagio():
    dados = {
        "routes": [{
            "distanceMeters": 12345, "duration": "600s",
            "travelAdvisory": {"tollInfo": {"estimatedPrice": [{"units": "10", "nanos": 500000000, "currencyCode": "BRL"}]}},
        }],
    }
    resultado = asyncio.run(geo._rota_google(_ClienteFake(_RespostaFake(dados)), -22.9, -47.1, -23.5, -46.6))
    assert resultado["distancia_km"] == 12
    assert resultado["duracao_min"] == 10
    assert resultado["pedagio_valor"] == pytest.approx(10.5)
    assert resultado["pedagio_moeda"] == "BRL"


def test_rota_google_sucesso_sem_pedagio():
    dados = {"routes": [{"distanceMeters": 5000, "duration": "300s"}]}
    resultado = asyncio.run(geo._rota_google(_ClienteFake(_RespostaFake(dados)), -22.9, -47.1, -23.5, -46.6))
    assert resultado["pedagio_valor"] is None
    assert resultado["pedagio_moeda"] is None


def test_rota_google_sem_rotas_da_erro():
    dados = {"routes": []}
    with pytest.raises(geo.GeoError, match="Google Maps"):
        asyncio.run(geo._rota_google(_ClienteFake(_RespostaFake(dados)), -22.9, -47.1, -23.5, -46.6))


def test_rota_google_erro_de_conexao():
    cliente = _ClienteFake(erro_conexao=httpx.ConnectError("falha de rede"))
    with pytest.raises(geo.GeoError, match="Falha ao calcular"):
        asyncio.run(geo._rota_google(cliente, -22.9, -47.1, -23.5, -46.6))
