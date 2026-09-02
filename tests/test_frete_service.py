# Desenvolvedor Chefe: RenanFolha

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
            nome="VUC", de=0, ate=1000, tarifa_km=2.0,
            valor_tonelada_excedente=1.0, tarifa_km_retorno=0.5, tarifa_km_manutencao=0.1,
            capacidade_m3=10,
        ),
        "truck": fs.Veiculo(
            nome="Truck", de=1000, ate=999999, tarifa_km=3.0,
            valor_tonelada_excedente=800.0, capacidade_m3=30,
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
    p.taxas_balsa = [
        fs.TaxaBalsa(cidade_origem="Belém", cidade_destino="Macapá", veiculo="VUC", tipo="fixo", valor=120.0),
    ]
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
    # peso (50kg) está bem dentro da faixa do VUC (até 1000kg) -> sem
    # excedente, o veículo já cobre esse peso normalmente.
    assert calc["peso_excedente_kg"] == pytest.approx(0.0)
    assert calc["custo_peso_excedente"] == pytest.approx(0.0)
    assert calc["frete_ajustado"] == pytest.approx(200.0)
    assert calc["custo_manutencao"] == pytest.approx(10.0)
    assert calc["custo_taxas_adicionais"] == pytest.approx(10.0)
    assert resultado["resultado"]["frete_total"] == pytest.approx(220.0)
    assert calc["faixa_km_aplicada"] is False
    assert calc["tarifa_km_veiculo"] == pytest.approx(2.0)  # tarifa_km fixa do VUC, sem faixa cadastrada


def test_peso_dentro_da_faixa_do_veiculo_nao_gera_excedente(parametros):
    # peso=1500 fica dentro da faixa do Truck (1000-999999) -- mesmo o
    # Truck tendo valor_tonelada_excedente configurado (800.0), não deve
    # cobrar nada, porque o veículo escolhido já cobre esse peso normalmente.
    resultado = fs.calcular_orcamento(
        peso=1500, paletes=_paletes(), distancia=10, valor_mercadoria=100,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
    )
    assert resultado["entrada"]["veiculo"] == "Truck"
    calc = resultado["calculos_intermediarios"]
    assert calc["peso_excedente_kg"] == pytest.approx(0.0)
    assert calc["custo_peso_excedente"] == pytest.approx(0.0)


def test_peso_excedente_so_aplica_acima_do_ate_do_maior_veiculo(parametros):
    # nenhum veículo cobre pesos acima de 2000kg nesse cenário --
    # buscar_veiculo_por_peso cai no fallback (usa o maior veículo mesmo
    # assim) e o excedente vira sobretaxa pelos kg que passaram do
    # limite máximo disponível (ver comentário em calcular_orcamento).
    parametros.veiculos["truck"].ate = 2000
    parametros.veiculos_por_peso = sorted(parametros.veiculos.values(), key=lambda v: v.de)
    resultado = fs.calcular_orcamento(
        peso=2500, paletes=_paletes(), distancia=10, valor_mercadoria=100,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
    )
    assert resultado["entrada"]["veiculo"] == "Truck"
    calc = resultado["calculos_intermediarios"]
    # excedente = 2500 - 2000 (até do Truck) = 500kg = 0.5 tonelada * R$800/ton = 400
    assert calc["peso_excedente_kg"] == pytest.approx(500.0)
    assert calc["custo_peso_excedente"] == pytest.approx(400.0)


def test_valor_excedente_e_por_tonelada_nao_por_kg(parametros):
    # regressão: valor_tonelada_excedente já se chamou valor_kg_excedente
    # e multiplicava direto pelo kg, gerando um custo 1000x maior que o
    # pretendido (ex: R$220/tonelada virava R$220/kg sem querer).
    parametros.veiculos["truck"].ate = 10000
    parametros.veiculos["truck"].valor_tonelada_excedente = 220.0
    parametros.veiculos_por_peso = sorted(parametros.veiculos.values(), key=lambda v: v.de)
    resultado = fs.calcular_orcamento(
        peso=12000, paletes=_paletes(), distancia=10, valor_mercadoria=100,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
    )
    calc = resultado["calculos_intermediarios"]
    # excedente = 12000 - 10000 = 2000kg = 2 toneladas * R$220/ton = 440
    assert calc["peso_excedente_kg"] == pytest.approx(2000.0)
    assert calc["custo_peso_excedente"] == pytest.approx(440.0)


def test_faixa_km_veiculo_substitui_tarifa_fixa(parametros):
    parametros.faixas_km_veiculo["vuc"] = [
        fs.FaixaKmVeiculo(veiculo="VUC", de=0, ate=100, tarifa_km=5.0),
        fs.FaixaKmVeiculo(veiculo="VUC", de=100, ate=999999, tarifa_km=3.0),
    ]
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=150, valor_mercadoria=100,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
    )
    calc = resultado["calculos_intermediarios"]
    assert calc["faixa_km_aplicada"] is True
    assert calc["tarifa_km_veiculo"] == pytest.approx(3.0)  # faixa 100-999999, não o tarifa_km fixo (2.0)
    assert calc["custo_km"] == pytest.approx(450.0)  # 150km * 3.0


def test_faixa_km_veiculo_cai_pra_tarifa_fixa_abaixo_da_menor_faixa(parametros):
    parametros.faixas_km_veiculo["vuc"] = [
        fs.FaixaKmVeiculo(veiculo="VUC", de=200, ate=999999, tarifa_km=3.0),
    ]
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=50, valor_mercadoria=100,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
    )
    calc = resultado["calculos_intermediarios"]
    assert calc["faixa_km_aplicada"] is False
    assert calc["tarifa_km_veiculo"] == pytest.approx(2.0)  # abaixo da menor faixa -> volta pro fixo do VUC


def test_faixa_km_veiculo_nao_afeta_outro_veiculo(parametros):
    # faixa só cadastrada pro VUC -- Truck continua com tarifa_km fixa
    parametros.faixas_km_veiculo["vuc"] = [
        fs.FaixaKmVeiculo(veiculo="VUC", de=0, ate=999999, tarifa_km=99.0),
    ]
    resultado = fs.calcular_orcamento(
        peso=1500, paletes=_paletes(), distancia=50, valor_mercadoria=100,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
    )
    assert resultado["entrada"]["veiculo"] == "Truck"
    calc = resultado["calculos_intermediarios"]
    assert calc["faixa_km_aplicada"] is False
    assert calc["tarifa_km_veiculo"] == pytest.approx(3.0)  # tarifa_km fixa do Truck


def test_manutencao_incide_tambem_sobre_retorno_vazio(parametros):
    # VUC no fixture: tarifa_km_manutencao=0.1, tarifa_km_retorno=0.5
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        distancia_retorno=40,
    )
    calc = resultado["calculos_intermediarios"]
    # manutenção agora soma ida (100km) + retorno (40km) = 140km * 0.1
    assert calc["custo_manutencao"] == pytest.approx(14.0)
    assert calc["distancia_manutencao_km"] == 140
    assert calc["custo_retorno"] == pytest.approx(20.0)  # só o retorno: 40km * 0.5


def test_manutencao_incide_sobre_coleta_com_frota_propria(parametros):
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        distancia_coleta=20, cidade_coleta="Alguma Cidade, SP, Brasil", cidade_origem="SP",
    )
    calc = resultado["calculos_intermediarios"]
    # manutenção soma ida (100km) + coleta com frota própria (20km) = 120km * 0.1
    assert calc["custo_manutencao"] == pytest.approx(12.0)
    assert calc["distancia_manutencao_km"] == 120


def test_manutencao_nao_incide_sobre_coleta_terceirizada(parametros):
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        distancia_coleta=20, coleta_terceirizada=True, valor_coleta_terceirizada=50,
    )
    calc = resultado["calculos_intermediarios"]
    # coleta foi da transportadora contratada, não da frota própria -> só a ida conta
    assert calc["custo_manutencao"] == pytest.approx(10.0)


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


def test_quantidade_do_palete_multiplica_o_volume(parametros):
    # 1 palete de 40x30x25 (0.03 m³) com quantidade=3 deve dar o mesmo
    # volume que 3 linhas iguais separadas -- evita ter que repetir a
    # linha manualmente quando os paletes são idênticos.
    paletes_x3 = [{"comprimento": 40, "largura": 30, "altura": 25, "quantidade": 3}]
    paletes_repetidos = _paletes() + _paletes() + _paletes()

    resultado_x3 = fs.calcular_orcamento(
        peso=50, paletes=paletes_x3, distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="TesteVolume", sla="Padrão",
    )
    resultado_repetido = fs.calcular_orcamento(
        peso=50, paletes=paletes_repetidos, distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="TesteVolume", sla="Padrão",
    )
    assert resultado_x3["calculos_intermediarios"]["volume_total_m3"] == pytest.approx(0.09)
    assert (
        resultado_x3["calculos_intermediarios"]["volume_total_m3"]
        == resultado_repetido["calculos_intermediarios"]["volume_total_m3"]
    )


def test_quantidade_padrao_e_1_quando_nao_informada(parametros):
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
    )
    assert resultado["calculos_intermediarios"]["volume_total_m3"] == pytest.approx(0.03)


def test_quantidade_menor_que_1_e_rejeitada(parametros):
    paletes = [{"comprimento": 40, "largura": 30, "altura": 25, "quantidade": 0}]
    with pytest.raises(fs.FreteInputError, match="quantidade"):
        fs.calcular_orcamento(
            peso=50, paletes=paletes, distancia=100, valor_mercadoria=1000,
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


def test_percentual_capacidade_util_e_editavel_por_veiculo(parametros):
    # VUC tem capacidade_m3=10; com o percentual padrão (80%) o volume de
    # 6 m³ caberia (usável = 8 m³) e não subiria pro Truck. Reduzindo o
    # percentual do VUC pra 50% (usável = 5 m³), o mesmo volume deve
    # forçar a troca -- prova que o percentual configurado por veículo é
    # o que vale, não mais um 80% fixo no código.
    parametros.veiculos["vuc"].percentual_capacidade_util = 50
    paletes = _paletes(comprimento=200, largura=200, altura=150)  # 6 m³
    resultado = fs.calcular_orcamento(
        peso=50, paletes=paletes, distancia=10, valor_mercadoria=100,
        categoria="Geral", transporte="TesteVolume", sla="Padrão",
    )
    assert resultado["entrada"]["veiculo"] == "Truck"
    calc = resultado["calculos_intermediarios"]
    assert calc["percentual_capacidade_util_veiculo"] == 80  # Truck ficou no padrão


def test_volume_excede_todos_os_veiculos_disponiveis(parametros):
    paletes = _paletes(comprimento=1000, largura=1000, altura=1000)  # 1000 m³
    with pytest.raises(fs.FreteInputError, match="ultrapassa a capacidade útil configurada"):
        fs.calcular_orcamento(
            peso=50, paletes=paletes, distancia=10, valor_mercadoria=100,
            categoria="Geral", transporte="TesteVolume", sla="Padrão",
        )


def test_coleta_fixa_por_cidade_sobrepoe_faixa_por_km(parametros):
    parametros.coleta_cidades_fixas = [
        fs.ColetaCidadeFixa(filial_origem="SP", cidade_destino="Alguma Cidade", veiculo="VUC", valor_fixo=99.0),
    ]
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=100,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        distancia_coleta=20, cidade_coleta="Alguma Cidade, SP, Brasil", cidade_origem="SP",
    )
    calc = resultado["calculos_intermediarios"]
    assert calc["coleta_fixa_por_cidade"] is True
    assert calc["custo_coleta"] == pytest.approx(99.0)


def test_coleta_usa_faixa_por_km_quando_nao_ha_preco_fixo(parametros):
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


def test_taxa_regional_lista_de_cidades_aplica_em_qualquer_uma(parametros):
    # uma taxa regional cobrindo várias cidades numa linha só (mesmo
    # padrão de coleta_cidades_fixas) -- qualquer uma delas dispara a taxa
    parametros.taxas_regionais = [
        fs.TaxaRegional(cidade="Manaus, Boa Vista", nome="Área de Risco", tipo="fixo", valor=30.0),
    ]
    for cidade in ("Manaus, Amazonas, Brasil", "Boa Vista, Roraima, Brasil"):
        resultado = fs.calcular_orcamento(
            peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=100,
            categoria="Geral", transporte="Rodoviário", sla="Padrão",
            cidade_origem=cidade,
        )
        assert resultado["calculos_intermediarios"]["custo_taxas_regionais"] == pytest.approx(30.0)


def test_taxa_balsa_aplicada_na_direcao_e_veiculo_certos(parametros):
    # peso=50 escolhe o veículo "VUC" no fixture de teste (única faixa que cobre 50kg)
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        cidade_origem="Belém, Pará, Brasil", cidade_destino="Macapá, Amapá, Brasil",
    )
    calc = resultado["calculos_intermediarios"]
    assert calc["custo_balsa"] == pytest.approx(120.0)
    assert calc["taxa_balsa"]["veiculo"] == "VUC"


def test_taxa_balsa_aplicada_com_grafia_diferente_do_cadastro(parametros):
    # taxa cadastrada como "Belém" (com acento) deve bater mesmo quando a
    # rota chega com grafia diferente (ex: nome de filial sem acento) --
    # sem isso, uma filial cadastrada como "Belem" nunca bateria contra
    # uma taxa de balsa cadastrada como "Belém".
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        cidade_origem="Belem", cidade_destino="MACAPA",
    )
    assert resultado["calculos_intermediarios"]["custo_balsa"] == pytest.approx(120.0)


def test_taxa_balsa_nao_aplicada_na_direcao_invertida(parametros):
    # a mesma travessia, mas cotada no sentido contrário -- taxa é
    # direcional, não deve aplicar sem uma linha cadastrada pra essa volta
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        cidade_origem="Macapá, Amapá, Brasil", cidade_destino="Belém, Pará, Brasil",
    )
    assert resultado["calculos_intermediarios"]["custo_balsa"] == pytest.approx(0.0)


def test_taxa_balsa_nao_aplicada_para_outro_veiculo(parametros):
    # mesma rota, mas o peso agora escolhe o "Truck" (faixa >=1000kg no
    # fixture) -- a taxa de balsa só foi cadastrada pro VUC
    resultado = fs.calcular_orcamento(
        peso=1500, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        cidade_origem="Belém, Pará, Brasil", cidade_destino="Macapá, Amapá, Brasil",
    )
    calc = resultado["calculos_intermediarios"]
    assert calc["custo_balsa"] == pytest.approx(0.0)
    # avisa que a rota bateu, só não pro veículo escolhido (Truck) -- em
    # vez de zerar silenciosamente
    assert calc["balsa_outro_veiculo"] == ["VUC"]


def test_taxa_balsa_sem_aviso_quando_rota_nem_existe(parametros):
    # rota diferente (não cadastrada em nenhum veículo) -- não deve sugerir nada
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        cidade_origem="Curitiba, PR, Brasil", cidade_destino="Florianópolis, SC, Brasil",
    )
    assert resultado["calculos_intermediarios"]["balsa_outro_veiculo"] is None


def test_taxa_balsa_curinga_origem_vale_para_qualquer_cidade(parametros):
    # corredor fluvial: "*" -> "Manaus" precisa valer pra qualquer origem,
    # sem cadastrar uma linha por UF
    parametros.taxas_balsa.append(
        fs.TaxaBalsa(cidade_origem="*", cidade_destino="Manaus", veiculo="VUC", tipo="fixo", valor=7110.58)
    )
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        cidade_origem="São Paulo, SP, Brasil", cidade_destino="Manaus, Amazonas, Brasil",
    )
    assert resultado["calculos_intermediarios"]["custo_balsa"] == pytest.approx(7110.58)


def test_taxa_balsa_linha_especifica_vence_curinga(parametros):
    # Boa Vista -> Manaus é feito 100% por rodovia (BR-174), então uma
    # linha específica com valor 0 precisa sobrepor o curinga "*" -> Manaus
    parametros.taxas_balsa.append(
        fs.TaxaBalsa(cidade_origem="*", cidade_destino="Manaus", veiculo="VUC", tipo="fixo", valor=7110.58)
    )
    parametros.taxas_balsa.append(
        fs.TaxaBalsa(cidade_origem="Boa Vista", cidade_destino="Manaus", veiculo="VUC", tipo="fixo", valor=0.0)
    )
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        cidade_origem="Boa Vista, Roraima, Brasil", cidade_destino="Manaus, Amazonas, Brasil",
    )
    assert resultado["calculos_intermediarios"]["custo_balsa"] == pytest.approx(0.0)


def test_coleta_fixa_avisa_outro_veiculo_quando_nao_bate(parametros):
    parametros.coleta_cidades_fixas = [
        fs.ColetaCidadeFixa(filial_origem="SP", cidade_destino="Alguma Cidade", veiculo="Carreta", valor_fixo=50.0),
        fs.ColetaCidadeFixa(filial_origem="SP", cidade_destino="Alguma Cidade", veiculo="Truck", valor_fixo=60.0),
    ]
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=100,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        distancia_coleta=20, cidade_coleta="Alguma Cidade, SP, Brasil", cidade_origem="SP",
    )
    calc = resultado["calculos_intermediarios"]
    assert calc["coleta_fixa_por_cidade"] is False
    assert calc["coleta_fixa_outro_veiculo"] == ["Carreta", "Truck"]
    # continua caindo pra faixa por km normalmente, o aviso é só informativo
    assert calc["custo_coleta"] == pytest.approx(10 + 20 * 0.5)


def test_coleta_fixa_sem_aviso_quando_ja_aplicou(parametros):
    parametros.coleta_cidades_fixas = [
        fs.ColetaCidadeFixa(filial_origem="SP", cidade_destino="Alguma Cidade", veiculo="VUC", valor_fixo=99.0),
    ]
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=100,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        distancia_coleta=20, cidade_coleta="Alguma Cidade, SP, Brasil", cidade_origem="SP",
    )
    assert resultado["calculos_intermediarios"]["coleta_fixa_outro_veiculo"] is None


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
