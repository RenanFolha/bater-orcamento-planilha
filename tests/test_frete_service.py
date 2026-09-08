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


def test_rota_obrigatoria_ausente_por_padrao(parametros):
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
    )
    assert resultado["entrada"]["rota_obrigatoria"] is None


def test_rota_obrigatoria_aparece_na_memoria_de_calculo(parametros):
    # Vem de geo_service.calcular_distancia (nome da filial de escala) --
    # só informativo, não deve mexer em nenhum valor do frete.
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        prioridade_rota="Belem",
    )
    assert resultado["entrada"]["rota_obrigatoria"] == "Belem"
    assert resultado["resultado"]["frete_total"] == pytest.approx(220.0)


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


def test_prioridade_rota_curinga_origem_vale_para_qualquer_estado(parametros):
    # Manaus não tem acesso rodoviário direto -- "*" -> "Manaus" precisa
    # valer pra qualquer UF de origem, sem cadastrar uma linha por estado
    parametros.prioridades_rota.append(
        fs.PrioridadeRota(estado_origem="*", cidade_destino="Manaus", filial_escala="Belém")
    )
    achada = fs.prioridade_rota_aplicavel(parametros, "São Paulo, SP, Brasil", "Manaus, Amazonas, Brasil")
    assert achada is not None
    assert achada.filial_escala == "Belém"


def test_prioridade_rota_linha_especifica_vence_curinga(parametros):
    # Roraima -> Manaus é feito por rodovia (BR-174) via uma filial em Boa
    # Vista -- uma linha específica pra esse estado precisa sobrepor o
    # curinga "*" -> Manaus (que assume a via fluvial por Belém)
    parametros.prioridades_rota.append(
        fs.PrioridadeRota(estado_origem="*", cidade_destino="Manaus", filial_escala="Belém")
    )
    parametros.prioridades_rota.append(
        fs.PrioridadeRota(estado_origem="RR", cidade_destino="Manaus", filial_escala="Boa Vista")
    )
    achada = fs.prioridade_rota_aplicavel(parametros, "Boa Vista, Roraima, Brasil", "Manaus, Amazonas, Brasil")
    assert achada.filial_escala == "Boa Vista"


def test_prioridade_rota_nao_aplicada_quando_rota_nao_bate(parametros):
    parametros.prioridades_rota.append(
        fs.PrioridadeRota(estado_origem="*", cidade_destino="Manaus", filial_escala="Belém")
    )
    achada = fs.prioridade_rota_aplicavel(parametros, "São Paulo, SP, Brasil", "Curitiba, PR, Brasil")
    assert achada is None


def test_prioridade_rota_nao_aplicada_quando_uf_origem_nao_bate(parametros):
    # regra específica pro Pará -- origem de outro estado não deve casar
    parametros.prioridades_rota.append(
        fs.PrioridadeRota(estado_origem="PA", cidade_destino="Manaus", filial_escala="Belém")
    )
    achada = fs.prioridade_rota_aplicavel(parametros, "São Paulo, SP, Brasil", "Manaus, Amazonas, Brasil")
    assert achada is None


def test_aliquota_icms_curinga_vale_para_qualquer_uf(parametros):
    parametros.aliquotas_icms.append(fs.AliquotaIcms(estado_origem="*", estado_destino="*", aliquota=18.0))
    achada = fs.aliquota_icms_aplicavel(parametros, "São Paulo, SP, Brasil", "Curitiba, PR, Brasil")
    assert achada is not None
    assert achada.aliquota == pytest.approx(18.0)


def test_aliquota_icms_linha_especifica_vence_curinga(parametros):
    parametros.aliquotas_icms.append(fs.AliquotaIcms(estado_origem="*", estado_destino="*", aliquota=18.0))
    parametros.aliquotas_icms.append(fs.AliquotaIcms(estado_origem="SP", estado_destino="RJ", aliquota=12.0))
    achada = fs.aliquota_icms_aplicavel(parametros, "São Paulo, SP, Brasil", "Rio de Janeiro, RJ, Brasil")
    assert achada.aliquota == pytest.approx(12.0)


def test_aliquota_icms_nao_aplicada_quando_rota_nao_bate(parametros):
    parametros.aliquotas_icms.append(fs.AliquotaIcms(estado_origem="SP", estado_destino="RJ", aliquota=12.0))
    achada = fs.aliquota_icms_aplicavel(parametros, "São Paulo, SP, Brasil", "Curitiba, PR, Brasil")
    assert achada is None


def test_aliquota_icms_aplica_gross_up_no_frete_total(parametros):
    # Gross-up "por dentro": o frete sem imposto (220) precisa continuar
    # sendo 88% do frete final quando a alíquota é 12% -- ou seja, o
    # frete final é 220 / (1 - 0.12) = 250, não um acréscimo simples de
    # 220 * 1.12 = 246.40.
    parametros.aliquotas_icms.append(fs.AliquotaIcms(estado_origem="SP", estado_destino="RJ", aliquota=12.0))
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        cidade_origem="São Paulo, SP, Brasil", cidade_destino="Rio de Janeiro, RJ, Brasil",
    )
    calc = resultado["calculos_intermediarios"]
    assert calc["frete_sem_icms"] == pytest.approx(220.0)
    assert calc["aliquota_icms_pct"] == pytest.approx(12.0)
    assert calc["valor_icms"] == pytest.approx(30.0, abs=0.01)
    assert resultado["resultado"]["frete_total"] == pytest.approx(250.0, abs=0.01)


def test_aliquota_icms_resolve_uf_da_filial_quando_origem_e_so_o_nome(parametros):
    # Quando a origem do orçamento é "Filial", o front manda só o nome da
    # filial (sem endereço, ver payload.cidade_origem em
    # routers/orcamento.py) -- o endereço cadastrado da filial normalmente
    # é só rua/número/bairro/CEP, sem cidade/UF (o nome da filial já é a
    # "cidade de referência"), então precisa usar a UF cadastrada
    # explicitamente na filial (fs.Filial.uf) em vez de tentar extrair do
    # texto do endereço.
    parametros.filiais["campinas"] = fs.Filial(
        "Campinas", "Rua Exemplo, 100, bairro Tal", None, None, uf="SP",
    )
    parametros.aliquotas_icms.append(fs.AliquotaIcms(estado_origem="SP", estado_destino="RJ", aliquota=12.0))
    achada = fs.aliquota_icms_aplicavel(parametros, "Campinas", "Rio de Janeiro, RJ, Brasil")
    assert achada is not None
    assert achada.aliquota == pytest.approx(12.0)


def test_aliquota_icms_resolve_uf_de_endereco_curto_cidade_uf(parametros):
    # Endereço digitado à mão sem passar pelo geocodificador -- só
    # "Cidade, UF" (2 segmentos), formato que cidade_e_uf sozinho não
    # reconhece (exige o formato completo do geocodificador).
    parametros.aliquotas_icms.append(fs.AliquotaIcms(estado_origem="SP", estado_destino="RJ", aliquota=12.0))
    achada = fs.aliquota_icms_aplicavel(parametros, "São Paulo, SP", "Rio de Janeiro, RJ")
    assert achada is not None
    assert achada.aliquota == pytest.approx(12.0)


def test_pis_cofins_aplica_gross_up_no_frete_total(parametros):
    # Mesmo raciocínio do gross-up de ICMS: o frete sem imposto (220)
    # precisa continuar sendo 90,75% do frete final quando a alíquota é
    # 9,25% -- 220 / (1 - 0,0925), não um acréscimo simples "por fora".
    parametros.aliquota_pis_cofins = 9.25
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        cidade_origem="São Paulo, SP, Brasil", cidade_destino="Curitiba, PR, Brasil",
    )
    calc = resultado["calculos_intermediarios"]
    esperado = 220.0 / (1 - 0.0925)  # == 220 / 0.9075
    assert calc["frete_sem_pis_cofins"] == pytest.approx(220.0)
    assert calc["aliquota_pis_cofins_pct"] == pytest.approx(9.25)
    assert calc["valor_pis_cofins"] == pytest.approx(esperado - 220.0, abs=0.01)
    assert resultado["resultado"]["frete_total"] == pytest.approx(esperado, abs=0.01)


def test_pis_cofins_e_aplicado_antes_do_icms(parametros):
    # PIS/COFINS entra primeiro (gross-up sobre o frete base), e o ICMS
    # incide por cima do frete que já saiu com PIS/COFINS embutido --
    # não dos dois impostos somados "por fora" nem do ICMS calculado
    # sobre o frete base original.
    parametros.aliquota_pis_cofins = 9.25
    parametros.aliquotas_icms.append(fs.AliquotaIcms(estado_origem="SP", estado_destino="RJ", aliquota=12.0))
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        cidade_origem="São Paulo, SP, Brasil", cidade_destino="Rio de Janeiro, RJ, Brasil",
    )
    calc = resultado["calculos_intermediarios"]
    frete_com_pis_cofins = 220.0 / (1 - 0.0925)
    frete_com_icms = frete_com_pis_cofins / (1 - 0.12)
    assert calc["frete_sem_pis_cofins"] == pytest.approx(220.0)
    assert calc["frete_sem_icms"] == pytest.approx(frete_com_pis_cofins, abs=0.01)
    assert resultado["resultado"]["frete_total"] == pytest.approx(frete_com_icms, abs=0.01)


def test_sem_aliquota_pis_cofins_frete_total_fica_igual(parametros):
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        cidade_origem="São Paulo, SP, Brasil", cidade_destino="Curitiba, PR, Brasil",
    )
    calc = resultado["calculos_intermediarios"]
    assert calc["aliquota_pis_cofins_pct"] == pytest.approx(0.0)
    assert calc["valor_pis_cofins"] == pytest.approx(0.0)
    assert resultado["resultado"]["frete_total"] == pytest.approx(220.0)


def test_sem_aliquota_cadastrada_frete_total_fica_igual(parametros):
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        cidade_origem="São Paulo, SP, Brasil", cidade_destino="Curitiba, PR, Brasil",
    )
    calc = resultado["calculos_intermediarios"]
    assert calc["aliquota_icms_pct"] == pytest.approx(0.0)
    assert calc["valor_icms"] == pytest.approx(0.0)
    assert resultado["resultado"]["frete_total"] == pytest.approx(220.0)


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


def test_pedagio_rota_sem_corredor_cadastrado_retorna_none(parametros):
    achado = fs.pedagio_rota_aplicavel(parametros, "Curitiba, PR, Brasil", "Florianópolis, SC, Brasil", 2)
    assert achado is None


def test_pedagio_rota_soma_todas_as_pracas_do_corredor(parametros):
    # Um corredor normalmente atravessa mais de uma praça -- diferente de
    # taxa de balsa (que escolhe uma linha vencedora), aqui todas as
    # praças do corredor mais específico entram na soma.
    parametros.pracas_pedagio = {
        1: fs.PracaPedagio(1, "Praça 5", "BR-101", "ViaSul", {2: 12.4, 3: 18.6}),
        2: fs.PracaPedagio(2, "Praça 8", "BR-101", "ViaSul", {2: 10.0, 3: 15.0}),
    }
    parametros.pedagios_rota = [
        fs.PedagioRota("Curitiba", "Florianópolis", 1),
        fs.PedagioRota("Curitiba", "Florianópolis", 2),
    ]
    total, pracas = fs.pedagio_rota_aplicavel(parametros, "Curitiba, PR, Brasil", "Florianópolis, SC, Brasil", 2)
    assert total == pytest.approx(22.4)
    assert set(pracas) == {"Praça 5", "Praça 8"}


def test_pedagio_rota_curinga_origem_vale_para_qualquer_origem(parametros):
    parametros.pracas_pedagio = {1: fs.PracaPedagio(1, "Praça X", "BR-101", "ViaSul", {2: 20.0})}
    parametros.pedagios_rota = [fs.PedagioRota("*", "Manaus", 1)]
    total, pracas = fs.pedagio_rota_aplicavel(parametros, "São Paulo, SP, Brasil", "Manaus, Amazonas, Brasil", 2)
    assert total == pytest.approx(20.0)
    assert pracas == ["Praça X"]


def test_pedagio_rota_linha_especifica_vence_curinga(parametros):
    parametros.pracas_pedagio = {
        1: fs.PracaPedagio(1, "Praça Curinga", "BR-101", "ViaSul", {2: 20.0}),
        2: fs.PracaPedagio(2, "Praça Específica", "BR-116", "Arteris", {2: 30.0}),
    }
    parametros.pedagios_rota = [
        fs.PedagioRota("*", "Manaus", 1),
        fs.PedagioRota("Belém", "Manaus", 2),
    ]
    total, pracas = fs.pedagio_rota_aplicavel(parametros, "Belém, PA, Brasil", "Manaus, Amazonas, Brasil", 2)
    assert total == pytest.approx(30.0)
    assert pracas == ["Praça Específica"]


def test_pedagio_rota_direcao_invertida_nao_bate(parametros):
    parametros.pracas_pedagio = {1: fs.PracaPedagio(1, "Praça 5", "BR-101", "ViaSul", {2: 12.4})}
    parametros.pedagios_rota = [fs.PedagioRota("Curitiba", "Florianópolis", 1)]
    achado = fs.pedagio_rota_aplicavel(parametros, "Florianópolis, SC, Brasil", "Curitiba, PR, Brasil", 2)
    assert achado is None


def test_pedagio_rota_sem_preco_pro_numero_de_eixos_retorna_none(parametros):
    parametros.pracas_pedagio = {1: fs.PracaPedagio(1, "Praça 5", "BR-101", "ViaSul", {2: 12.4})}
    parametros.pedagios_rota = [fs.PedagioRota("Curitiba", "Florianópolis", 1)]
    # a praça não tem preço cadastrado pra 6 eixos (0 == "não cadastrado")
    achado = fs.pedagio_rota_aplicavel(parametros, "Curitiba, PR, Brasil", "Florianópolis, SC, Brasil", 6)
    assert achado is None


def test_pedagio_rota_sem_numero_de_eixos_retorna_none(parametros):
    parametros.pracas_pedagio = {1: fs.PracaPedagio(1, "Praça 5", "BR-101", "ViaSul", {2: 12.4})}
    parametros.pedagios_rota = [fs.PedagioRota("Curitiba", "Florianópolis", 1)]
    achado = fs.pedagio_rota_aplicavel(parametros, "Curitiba, PR, Brasil", "Florianópolis, SC, Brasil", 0)
    assert achado is None


def test_distancia_fixa_sem_corredor_cadastrado_retorna_none(parametros):
    achado = fs.distancia_fixa_aplicavel(parametros, "São Paulo, SP, Brasil", "Manaus, Amazonas, Brasil")
    assert achado is None


def test_distancia_fixa_corredor_exato(parametros):
    parametros.distancias_fixas = [fs.DistanciaFixa("Belém", "Manaus", 2096)]
    achado = fs.distancia_fixa_aplicavel(parametros, "Belém, Pará, Brasil", "Manaus, Amazonas, Brasil")
    assert achado is not None
    assert achado.distancia_km == 2096


def test_distancia_fixa_direcao_invertida_nao_bate(parametros):
    parametros.distancias_fixas = [fs.DistanciaFixa("Belém", "Manaus", 2096)]
    achado = fs.distancia_fixa_aplicavel(parametros, "Manaus, Amazonas, Brasil", "Belém, Pará, Brasil")
    assert achado is None


def test_distancia_fixa_curinga_e_especificidade(parametros):
    parametros.distancias_fixas = [
        fs.DistanciaFixa("*", "Manaus", 3000),
        fs.DistanciaFixa("Belém", "Manaus", 2096),
    ]
    # a linha específica (Belém -> Manaus) vence o curinga (* -> Manaus)
    achado = fs.distancia_fixa_aplicavel(parametros, "Belém, Pará, Brasil", "Manaus, Amazonas, Brasil")
    assert achado.distancia_km == 2096
    # origem diferente só bate no curinga
    achado2 = fs.distancia_fixa_aplicavel(parametros, "Fortaleza, CE, Brasil", "Manaus, Amazonas, Brasil")
    assert achado2.distancia_km == 3000
