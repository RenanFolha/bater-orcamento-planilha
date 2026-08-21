"""
Testes da lógica de cálculo de frete (frete_service.py). Não tocam no
banco de verdade: montam um ParametrosFrete em memória e substituem o
`parametros` global do módulo (monkeypatch), então cada teste roda
isolado e não depende do frete.db do ambiente.
"""

import pytest

import frete_service as fs


def _parametros_teste():
    p = fs.ParametrosFrete()
    p.veiculos = {
        "vuc": fs.Veiculo(
            nome="VUC", de=0, ate=1000, tarifa_km=2.0, peso_incluso_kg=100,
            valor_kg_excedente=1.0, tarifa_km_retorno=0.5, tarifa_km_manutencao=0.1,
            capacidade_m3=10,
        ),
        "truck": fs.Veiculo(
            nome="Truck", de=1000, ate=999999, tarifa_km=3.0, peso_incluso_kg=500,
            valor_kg_excedente=0.8, capacidade_m3=30,
        ),
    }
    p.veiculos_por_peso = sorted(p.veiculos.values(), key=lambda v: v.de)
    p.categorias = {"geral": fs.Categoria("Geral", 1.0)}
    p.transportes = {
        "rodoviário": fs.Transporte("Rodoviário", 1.0, fator_cubagem=3000),
        "testevolume": fs.Transporte("TesteVolume", 1.0, fator_cubagem=100_000),
    }
    p.slas = {"padrão": fs.SLA("Padrão", 1.0, prazo_dias=5)}
    p.filiais = {"sp": fs.Filial("SP", "Endereco Teste, São Paulo, SP", None, None)}
    p.faixas_coleta = [
        fs.FaixaDistancia(de=0, ate=50, taxa_fixa=10, tarifa_km=0.5),
        fs.FaixaDistancia(de=50, ate=999999, taxa_fixa=20, tarifa_km=0.3),
    ]
    p.taxas_adicionais = [fs.TaxaAdicional(nome="GRIS", tipo="percentual", valor=1.0)]
    p.taxas_regionais = [fs.TaxaRegional(cidade="Manaus", nome="Zona Franca", tipo="fixo", valor=50.0)]
    return p


@pytest.fixture
def parametros(monkeypatch):
    p = _parametros_teste()
    monkeypatch.setattr(fs, "parametros", p)
    return p


def _paletes(comprimento=40, largura=30, altura=25):
    return [{"comprimento": comprimento, "largura": largura, "altura": altura}]


def test_calculo_basico_sem_coleta(parametros):
    resultado = fs.calcular_orcamento(
        peso=50,
        paletes=_paletes(),
        distancia=100,
        valor_mercadoria=1000,
        categoria="Geral",
        transporte="Rodoviário",
        sla="Padrão",
    )
    calc = resultado["calculos_intermediarios"]

    assert resultado["entrada"]["veiculo"] == "VUC"
    assert calc["custo_km"] == pytest.approx(200.0)
    assert calc["peso_excedente_kg"] == pytest.approx(0.0)
    assert calc["frete_ajustado"] == pytest.approx(200.0)
    assert calc["custo_manutencao"] == pytest.approx(10.0)
    assert calc["custo_taxas_adicionais"] == pytest.approx(10.0)
    assert resultado["resultado"]["frete_total"] == pytest.approx(220.0)
    assert resultado["resultado"]["prazo_estimado_dias_uteis"] == 5


@pytest.mark.parametrize("campo,valor,mensagem", [
    ("peso", 0, "Peso deve ser maior que zero"),
    ("distancia", 0, "Distância deve ser maior que zero"),
    ("valor_mercadoria", -1, "não pode ser negativo"),
])
def test_validacoes_entrada_invalida(parametros, campo, valor, mensagem):
    kwargs = dict(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
    )
    kwargs[campo] = valor
    with pytest.raises(fs.FreteInputError, match=mensagem):
        fs.calcular_orcamento(**kwargs)


def test_paletes_vazios_rejeitados(parametros):
    with pytest.raises(fs.FreteInputError):
        fs.calcular_orcamento(
            peso=50, paletes=[], distancia=100, valor_mercadoria=1000,
            categoria="Geral", transporte="Rodoviário", sla="Padrão",
        )


def test_veiculo_por_peso_troca_de_faixa(parametros):
    resultado = fs.calcular_orcamento(
        peso=1500, paletes=_paletes(), distancia=50, valor_mercadoria=100,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
    )
    assert resultado["entrada"]["veiculo"] == "Truck"


def test_upgrade_de_veiculo_por_volume(parametros):
    # peso baixo (fica na faixa do VUC) mas volume grande (3m x 3m x 1m) —
    # com fator_cubagem alto o peso cubado não empurra pro Truck sozinho,
    # então quem decide a troca é o limite de 80% da capacidade em m³.
    paletes = _paletes(comprimento=300, largura=300, altura=100)  # 9 m³
    resultado = fs.calcular_orcamento(
        peso=50, paletes=paletes, distancia=10, valor_mercadoria=100,
        categoria="Geral", transporte="TesteVolume", sla="Padrão",
    )
    assert resultado["entrada"]["veiculo"] == "Truck"
    assert resultado["calculos_intermediarios"]["volume_total_m3"] == pytest.approx(9.0)


def test_volume_excede_todos_os_veiculos_disponiveis(parametros):
    paletes = _paletes(comprimento=1000, largura=1000, altura=1000)  # 1000 m³
    with pytest.raises(fs.FreteInputError, match="ultrapassa 80%"):
        fs.calcular_orcamento(
            peso=50, paletes=paletes, distancia=10, valor_mercadoria=100,
            categoria="Geral", transporte="TesteVolume", sla="Padrão",
        )


def test_coleta_fixa_por_cidade_sobrepoe_faixa_por_km(parametros, monkeypatch):
    monkeypatch.setattr(
        fs.db, "buscar_coleta_cidade_fixa",
        lambda filial_origem, cidade_destino, veiculo: {"valor_fixo": 99.0},
    )
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=100,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        distancia_coleta=20, cidade_coleta="Alguma Cidade, SP, Brasil", cidade_origem="SP",
    )
    calc = resultado["calculos_intermediarios"]
    assert calc["coleta_fixa_por_cidade"] is True
    assert calc["custo_coleta"] == pytest.approx(99.0)


def test_coleta_usa_faixa_por_km_quando_nao_ha_preco_fixo(parametros, monkeypatch):
    monkeypatch.setattr(fs.db, "buscar_coleta_cidade_fixa", lambda *a, **k: None)
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=100,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        distancia_coleta=20, cidade_coleta="Alguma Cidade, SP, Brasil", cidade_origem="SP",
    )
    calc = resultado["calculos_intermediarios"]
    # faixa 0-50: taxa_fixa=10 + 20km * 0.5/km = 20 -> total 20
    assert calc["coleta_fixa_por_cidade"] is False
    assert calc["custo_coleta"] == pytest.approx(10 + 20 * 0.5)


def test_taxa_regional_aplicada_por_cidade_de_origem(parametros):
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=100,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        cidade_origem="Manaus, Amazonas, Brasil",
    )
    calc = resultado["calculos_intermediarios"]
    assert calc["custo_taxas_regionais"] == pytest.approx(50.0)
    assert calc["taxas_regionais"][0]["nome"] == "Zona Franca"


def test_taxa_regional_nao_aplicada_para_outra_cidade(parametros):
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=100,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        cidade_origem="Curitiba, PR, Brasil",
    )
    assert resultado["calculos_intermediarios"]["custo_taxas_regionais"] == pytest.approx(0.0)


def test_categoria_invalida_gera_erro_com_opcoes(parametros):
    with pytest.raises(fs.FreteInputError, match="Geral"):
        fs.calcular_orcamento(
            peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=100,
            categoria="Categoria Inexistente", transporte="Rodoviário", sla="Padrão",
        )


@pytest.mark.parametrize("endereco,esperado", [
    # Formato típico do Nominatim (provedor padrão, sem GOOGLE_MAPS_API_KEY) —
    # estado por extenso, não a sigla de 2 letras.
    ("Rua Augusta, 500, São Paulo, São Paulo, Brasil", "São Paulo"),
    ("Av. Paulista, 1000, Bela Vista, São Paulo, São Paulo, 01310-100, Brasil", "São Paulo"),
    ("Manaus, Região Geográfica Imediata de Manaus, Amazonas, Brasil", "Manaus"),
    ("Filial Única", "Filial Única"),
    ("", None),
    # UF como sigla em segmento próprio (ex: endereço digitado manualmente).
    ("Rua Augusta, 500, São Paulo, SP, Brasil", "São Paulo"),
    # formatted_address do Google Maps: sigla colada no segmento da cidade
    # (com hífen), sem estado por extenso nenhum na string.
    ("R. Exemplo, 100 - Centro, Manaus - AM, 69000-000, Brazil", "Manaus"),
    ("Av. Paulista, 1578 - Bela Vista, São Paulo - SP, 01310-200, Brazil", "São Paulo"),
    ("Manaus - AM", "Manaus"),
])
def test_cidade_da_retirada(endereco, esperado):
    assert fs._cidade_da_retirada(endereco) == esperado
