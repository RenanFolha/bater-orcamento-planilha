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
