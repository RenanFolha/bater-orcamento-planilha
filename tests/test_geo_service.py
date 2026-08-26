"""
Testes de geo_service._buscar_rota_no_historico / calcular_distancia:
antes de chamar o serviço externo de geolocalização, uma rota (por
cidade, nas duas direções) E o mesmo veículo já cotados juntos e salvos
no histórico devem ser reaproveitados em vez de gastar uma
geocodificação nova. Usa o fixture `banco_temporario` (conftest.py) —
nunca toca no frete.db real nem em rede de verdade.
"""

import asyncio

import frete_db as db
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
