# Desenvolvedor Chefe: RenanFolha

"""
Testes da lógica de cálculo de frete (frete_service.py). Não tocam no
banco de verdade: montam um ParametrosFrete em memória e substituem o
`parametros` global do módulo (monkeypatch), então cada teste roda
isolado e não depende do frete.db do ambiente.
"""

import pytest

import frete_db as db
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
    # sem praça de pedágio cadastrada (veículos de teste não têm
    # numero_eixos) -> cai no fallback de 4% sobre frete + custos
    # operacionais + taxas (com PIS/COFINS e ICMS previstos por cima, sem
    # margem -- aqui ambos 0%): 4% de (frete_ajustado=200 +
    # custo_manutencao=10 + custo_taxas_adicionais=10) = 4% de 220 = 8,8
    # (ver fs.PEDAGIO_PCT_FALLBACK/_pedagio_aplicado)
    assert calc["pedagio"] == pytest.approx(8.8)
    assert calc["pedagio_estimado_pct"] == pytest.approx(4.0)
    # custo da operação=218,8 (frete_ajustado=200 + custo_manutencao=10 +
    # pedagio=8,8, SEM a taxa adicional) + impostos/taxas=10 + margem=40%
    # de 218,8=87,52 -> 316,32, mas o piso de markup mínimo (1.4x de
    # custo+taxas=228,8 -> 320,32) exige mais 4 de ajuste (ver
    # test_piso_markup_minimo_ajusta_taxas_pra_bater_1_4x)
    assert resultado["resultado"]["frete_total"] == pytest.approx(320.32)
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
    assert resultado["resultado"]["frete_total"] == pytest.approx(320.32)  # ver test_calculo_basico_sem_coleta


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


def test_retorno_que_cruza_balsa_cadastrada_cobra_taxa_de_balsa_em_vez_de_km(parametros):
    # Taxa de balsa cadastrada pra volta (Manaus -> Belem) além da de ida
    # (Belem -> Manaus, cadastrada em outro teste) -- a balsa é cobrada
    # sempre que a rota passa por ela, ida OU volta (taxas direcionais
    # independentes, ver _taxa_balsa_aplicavel). O retorno vazio, nesse
    # caso, não roda km de estrada -- só a taxa de balsa é cobrada.
    parametros.taxas_balsa = [
        fs.TaxaBalsa(cidade_origem="Manaus", cidade_destino="Belém", veiculo="VUC", tipo="fixo", valor=500.0),
    ]
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        cidade_origem="São Paulo, SP, Brasil", cidade_destino="Manaus, Amazonas, Brasil",
        distancia_retorno=2096, filial_retorno="Belém",
    )
    calc = resultado["calculos_intermediarios"]
    assert calc["custo_retorno"] == pytest.approx(0.0)  # não cobra km, só a balsa
    assert calc["distancia_manutencao_km"] == 100  # só a ida, sem o retorno de balsa
    assert calc["taxa_balsa_retorno"]["cidade_origem"] == "Manaus"
    assert calc["taxa_balsa_retorno"]["cidade_destino"] == "Belém"
    assert calc["custo_balsa"] == pytest.approx(500.0)  # só a volta (sem taxa cadastrada pra ida aqui)


def test_retorno_sem_taxa_de_balsa_cadastrada_continua_cobrando_por_km(parametros):
    # Mesmo com balsa na ida, sem uma taxa cadastrada especificamente pra
    # essa direção de retorno (destino -> filial), o retorno continua
    # cobrando por km normalmente -- só troca de comportamento quando bate
    # uma taxa cadastrada.
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        distancia_retorno=40, filial_retorno="Filial Sem Balsa Cadastrada",
    )
    calc = resultado["calculos_intermediarios"]
    assert calc["taxa_balsa_retorno"] is None
    assert calc["custo_retorno"] == pytest.approx(20.0)  # 40km * 0.5 (tarifa_km_retorno do VUC)
    assert calc["distancia_manutencao_km"] == 140


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


def test_diaria_veiculo_aplicada_na_retirada_no_cliente_em_am(parametros):
    parametros.taxas_diaria_veiculo = [fs.TaxaDiariaVeiculo(uf="AM", valor_carreta=220.0, valor_cavalo=819.0)]
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        distancia_coleta=20, cidade_coleta="Manaus, Amazonas, Brasil", cidade_origem="SP",
    )
    calc = resultado["calculos_intermediarios"]
    assert calc["custo_diaria_veiculo"] == pytest.approx(1039.0)
    assert calc["diaria_veiculo"] == {"uf": "AM", "valor_carreta": 220.0, "valor_cavalo": 819.0}


def test_diaria_veiculo_aplicada_na_entrega_no_cliente_em_am(parametros):
    parametros.taxas_diaria_veiculo = [fs.TaxaDiariaVeiculo(uf="AM", valor_carreta=220.0, valor_cavalo=819.0)]
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        cidade_origem="São Paulo, SP, Brasil", cidade_destino="Manaus, Amazonas, Brasil",
    )
    calc = resultado["calculos_intermediarios"]
    assert calc["custo_diaria_veiculo"] == pytest.approx(1039.0)


def test_diaria_veiculo_nao_dobra_quando_retirada_e_entrega_batem_no_am(parametros):
    parametros.taxas_diaria_veiculo = [fs.TaxaDiariaVeiculo(uf="AM", valor_carreta=220.0, valor_cavalo=819.0)]
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        distancia_coleta=20, cidade_coleta="Manaus, Amazonas, Brasil", cidade_origem="Manaus, Amazonas, Brasil",
        cidade_destino="Manaus, Amazonas, Brasil",
    )
    calc = resultado["calculos_intermediarios"]
    # mesma carreta/cavalo parados, não duas -- cobra só uma vez mesmo com
    # coleta E entrega batendo na mesma UF.
    assert calc["custo_diaria_veiculo"] == pytest.approx(1039.0)


def test_diaria_veiculo_nao_aplica_quando_coleta_e_entrega_terceirizadas(parametros):
    parametros.taxas_diaria_veiculo = [fs.TaxaDiariaVeiculo(uf="AM", valor_carreta=220.0, valor_cavalo=819.0)]
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        distancia_coleta=20, cidade_coleta="Manaus, Amazonas, Brasil", cidade_origem="SP",
        coleta_terceirizada=True, valor_coleta_terceirizada=50,
        cidade_destino="Manaus, Amazonas, Brasil", entrega_terceirizada=True, valor_entrega_terceirizada=80,
    )
    calc = resultado["calculos_intermediarios"]
    # frota própria não chegou a ir no cliente em nenhuma das duas pontas
    # -- quem rodou foi a transportadora contratada.
    assert calc["custo_diaria_veiculo"] == pytest.approx(0.0)
    assert calc["diaria_veiculo"] is None


def test_diaria_veiculo_nao_aplica_fora_da_uf_cadastrada(parametros):
    parametros.taxas_diaria_veiculo = [fs.TaxaDiariaVeiculo(uf="AM", valor_carreta=220.0, valor_cavalo=819.0)]
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        cidade_origem="São Paulo, SP, Brasil", cidade_destino="Rio de Janeiro, RJ, Brasil",
    )
    calc = resultado["calculos_intermediarios"]
    assert calc["custo_diaria_veiculo"] == pytest.approx(0.0)


def test_diaria_veiculo_nao_aplica_sem_tabela_cadastrada(parametros):
    # parametros.taxas_diaria_veiculo fica [] (default do fixture) -- sem
    # nenhuma UF cadastrada, a diária nunca é cobrada, mesmo em Manaus.
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        cidade_origem="São Paulo, SP, Brasil", cidade_destino="Manaus, Amazonas, Brasil",
    )
    calc = resultado["calculos_intermediarios"]
    assert calc["custo_diaria_veiculo"] == pytest.approx(0.0)


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


def test_margem_lucro_e_40_por_cento_so_do_custo_da_operacao(parametros):
    # Margem de lucro é fixa em 40% (ver fs.MARGEM_LUCRO_PADRAO) -- não é
    # mais um parâmetro digitável, e o VALOR em R$ é calculado só sobre
    # total_custo_operacao (frete_ajustado + custo_manutencao etc.), NÃO
    # sobre impostos/taxas cadastradas nem sobre PIS/COFINS/ICMS (ver
    # test_pis_cofins_e_icms_aplicados_antes_da_margem_de_lucro pra ver a
    # diferença quando há impostos).
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
    )
    calc = resultado["calculos_intermediarios"]
    # custo da operação = frete_ajustado=200 + custo_manutencao=10 +
    # pedagio=8,8 (fallback de 4% sem praça cadastrada, ver
    # test_calculo_basico_sem_coleta) = 218,8 (a taxa adicional de 10 é
    # "impostos e taxas", fora da base da margem)
    assert calc["total_custo_operacao"] == pytest.approx(218.8)
    # frete antes da margem = custo da operação (218,8) + impostos/taxas (10) = 228,8
    assert calc["frete_sem_margem_lucro"] == pytest.approx(228.8)
    assert calc["valor_margem_lucro"] == pytest.approx(87.52)  # 218,8 * 0.40, não 228,8 * 0.40
    # 228,8 + 87,52 = 316,32, mas o piso de markup mínimo (1.4x de 228,8 =
    # 320,32) ainda exige mais 4 de ajuste na linha de taxas (ver
    # test_piso_markup_minimo_ajusta_taxas_pra_bater_1_4x)
    assert calc["ajuste_piso_markup"] == pytest.approx(4.0)
    assert resultado["resultado"]["frete_total"] == pytest.approx(320.32)


def test_margem_lucro_padrao_e_40_por_cento(parametros):
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=100,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
    )
    assert resultado["calculos_intermediarios"]["margem_lucro_pct"] == 40


# ============================================================
# Piso de markup mínimo (1.4x custo da operação + impostos/taxas) --
# ver fs.MARKUP_MINIMO/_aplicar_piso_markup. A margem de lucro fixa
# (40% só do custo da operação) sozinha nem sempre garante 1.4x sobre a
# base MAIOR (custo + impostos/taxas) quando as taxas são proporcionalmente
# grandes -- o que falta é somado direto na linha de impostos/taxas.
# ============================================================


def test_piso_markup_minimo_ajusta_taxas_pra_bater_1_4x(parametros):
    # Taxa adicional grande o bastante (relativa ao custo da operação) pra
    # a margem fixa de 40% sozinha não bater o markup mínimo de 1.4x sobre
    # custo+taxas -- o ajuste entra direto na linha de impostos/taxas, sem
    # passar de novo por PIS/COFINS/ICMS (nenhum cadastrado aqui).
    parametros.taxas_adicionais.append(fs.TaxaAdicional(nome="Seguro Extra", tipo="fixo", valor=2000.0))
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
    )
    calc = resultado["calculos_intermediarios"]
    # impostos/taxas = 10 (GRIS) + 2000 (Seguro Extra) = 2010; pedágio cai
    # no fallback de 4%, mas agora a base inclui essas taxas (ver
    # _pedagio_aplicado): 4% de (210 + 2010) = 88,8. custo da operação =
    # 210 + pedagio=88,8 = 298,8
    assert calc["total_custo_operacao"] == pytest.approx(298.8)
    # piso = (298,8 + 2010) * 1.4 = 3232,32; margem fixa (298,8*0.40=
    # 119,52) só chega em 2428,32 (2308,8+119,52) -- faltam 804, somados na
    # linha de taxas (2010 -> 2814, o ajuste não muda com o pedágio: depende
    # só das taxas cadastradas, 0.4 * 2010 = 804)
    assert calc["ajuste_piso_markup"] == pytest.approx(804.0)
    assert calc["total_impostos_taxas"] == pytest.approx(2814.0)
    assert resultado["resultado"]["frete_total"] == pytest.approx(3232.32)


def test_piso_markup_minimo_nao_ajusta_quando_ja_bate_sozinho(parametros):
    # Sem taxas relevantes, o próprio custo + margem fixa já supera o
    # piso de 1.4x -- nenhum ajuste.
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=0,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
    )
    calc = resultado["calculos_intermediarios"]
    assert calc["custo_taxas_adicionais"] == pytest.approx(0.0)  # GRIS é % do valor da mercadoria (0 aqui)
    assert calc["ajuste_piso_markup"] == pytest.approx(0.0)


# ============================================================
# GRIS e Ad Valorem digitáveis por orçamento -- substituem o % cadastrado
# de mesmo nome (nunca abaixo dele, ver fs._piso_taxa_customizavel).
# ============================================================


def test_gris_digitado_substitui_o_cadastrado(parametros):
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        gris_pct=5.0,  # cadastrado é 1.0% (ver _parametros_teste)
    )
    calc = resultado["calculos_intermediarios"]
    gris = next(t for t in calc["taxas_adicionais"] if t["nome"] == "GRIS")
    assert gris["valor_configurado"] == pytest.approx(5.0)
    assert gris["valor_aplicado"] == pytest.approx(50.0)  # 1000 * 5%


def test_gris_digitado_abaixo_do_cadastrado_gera_erro(parametros):
    with pytest.raises(fs.FreteInputError, match="GRIS"):
        fs.calcular_orcamento(
            peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
            categoria="Geral", transporte="Rodoviário", sla="Padrão",
            gris_pct=0.5,  # cadastrado é 1.0%
        )


def test_ad_valorem_digitado_sem_cadastro_ainda_assim_aplica(parametros):
    # Nenhum "Ad Valorem" cadastrado em _parametros_teste -- piso é 0%,
    # então qualquer valor >= 0 é aceito, mesmo sem entrada correspondente
    # na Tabela de Preços.
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        ad_valorem_pct=2.0,
    )
    calc = resultado["calculos_intermediarios"]
    ad_valorem = next(t for t in calc["taxas_adicionais"] if t["nome"] == "Ad Valorem")
    assert ad_valorem["valor_configurado"] == pytest.approx(2.0)
    assert ad_valorem["valor_aplicado"] == pytest.approx(20.0)  # 1000 * 2%


def test_ad_valorem_digitado_negativo_gera_erro(parametros):
    # Sem cadastro, o piso é 0% -- um valor negativo ainda assim é abaixo
    # do piso e é rejeitado.
    with pytest.raises(fs.FreteInputError, match="Ad Valorem"):
        fs.calcular_orcamento(
            peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
            categoria="Geral", transporte="Rodoviário", sla="Padrão",
            ad_valorem_pct=-1.0,
        )


def test_gris_cadastrado_como_fixo_bloqueia_o_campo_digitavel(parametros):
    # GRIS cadastrado em R$ fixo (não % do valor da mercadoria) -- um %
    # digitado no orçamento não tem como garantir que o resultado nunca
    # fique abaixo desse valor fixo (bases diferentes), então a
    # substituição é bloqueada por completo, não só limitada por um piso.
    parametros.taxas_adicionais = [
        t for t in parametros.taxas_adicionais if t.nome.strip().lower() != "gris"
    ]
    parametros.taxas_adicionais.append(fs.TaxaAdicional(nome="GRIS", tipo="fixo", valor=50.0))
    with pytest.raises(fs.FreteInputError, match="GRIS.*fixo"):
        fs.calcular_orcamento(
            peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
            categoria="Geral", transporte="Rodoviário", sla="Padrão",
            gris_pct=100.0,  # mesmo um valor alto -- ainda bloqueado, tipo errado
        )


def test_gris_e_ad_valorem_nao_informados_usa_cadastrado_sem_mudanca(parametros):
    # gris_pct/ad_valorem_pct=None (padrão) -- comportamento idêntico a
    # antes dessa funcionalidade existir.
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
    )
    calc = resultado["calculos_intermediarios"]
    gris = next(t for t in calc["taxas_adicionais"] if t["nome"] == "GRIS")
    assert gris["valor_configurado"] == pytest.approx(1.0)
    assert "Ad Valorem" not in [t["nome"] for t in calc["taxas_adicionais"]]


def test_custo_extra_soma_ao_frete_e_aparece_no_detalhamento(parametros):
    sem_extra = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=100,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
    )
    com_extra = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=100,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        custos_extras=[{"categoria": "Paletização", "valor": 40.0}, {"categoria": "Carga", "valor": 10.0}],
    )
    calc = com_extra["calculos_intermediarios"]
    assert calc["custo_extra_total"] == pytest.approx(50.0)
    assert calc["custos_extras"] == [
        {"categoria": "Paletização", "valor_aplicado": 40.0},
        {"categoria": "Carga", "valor_aplicado": 10.0},
    ]
    assert com_extra["resultado"]["frete_total"] > sem_extra["resultado"]["frete_total"]


def test_custo_extra_categoria_invalida_gera_erro(parametros):
    with pytest.raises(fs.FreteInputError):
        fs.calcular_orcamento(
            peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=100,
            categoria="Geral", transporte="Rodoviário", sla="Padrão",
            custos_extras=[{"categoria": "Categoria Inventada", "valor": 10.0}],
        )


def test_custo_extra_valor_negativo_gera_erro(parametros):
    with pytest.raises(fs.FreteInputError):
        fs.calcular_orcamento(
            peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=100,
            categoria="Geral", transporte="Rodoviário", sla="Padrão",
            custos_extras=[{"categoria": "Diversos", "valor": -10.0}],
        )


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


def test_prioridade_rota_none_quando_origem_ou_destino_vazio(parametros):
    parametros.prioridades_rota.append(
        fs.PrioridadeRota(estado_origem="*", cidade_destino="Manaus", filial_escala="Belém")
    )
    assert fs.prioridade_rota_aplicavel(parametros, "", "Manaus, Amazonas, Brasil") is None
    assert fs.prioridade_rota_aplicavel(parametros, "São Paulo, SP, Brasil", "") is None


def test_prioridade_rota_none_quando_destino_nao_identificavel(parametros):
    parametros.prioridades_rota.append(
        fs.PrioridadeRota(estado_origem="*", cidade_destino="Manaus", filial_escala="Belém")
    )
    assert fs.prioridade_rota_aplicavel(parametros, "São Paulo, SP, Brasil", " , , ") is None


def test_destino_tem_prioridade_rota_cadastrada(parametros):
    parametros.prioridades_rota.append(
        fs.PrioridadeRota(estado_origem="*", cidade_destino="Manaus", filial_escala="Belém")
    )
    assert fs.destino_tem_prioridade_rota_cadastrada(parametros, "Manaus, Amazonas, Brasil") is True
    assert fs.destino_tem_prioridade_rota_cadastrada(parametros, "Curitiba, PR, Brasil") is False


def test_destino_tem_prioridade_rota_cadastrada_com_entrada_vazia_ou_nao_identificavel(parametros):
    parametros.prioridades_rota.append(
        fs.PrioridadeRota(estado_origem="*", cidade_destino="Manaus", filial_escala="Belém")
    )
    assert fs.destino_tem_prioridade_rota_cadastrada(parametros, "") is False
    assert fs.destino_tem_prioridade_rota_cadastrada(parametros, None) is False
    assert fs.destino_tem_prioridade_rota_cadastrada(parametros, " , , ") is False


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


def test_aliquota_icms_aplica_gross_up_sobre_frete_com_margem(parametros):
    # ICMS "por dentro" (gross-up) calculado sobre o
    # frete total JÁ COM a margem de lucro embutida (a alíquota incide
    # sobre o valor total cobrado do cliente, que já inclui o próprio
    # ICMS). O ICMS cadastrado aqui (12%, SP->RJ) também entra na
    # pré-visualização de impostos que dimensiona o pedágio de fallback
    # (ver _pedagio_aplicado): 4% de ((frete_ajustado=200 +
    # custo_manutencao=10 + custo_taxas_adicionais=10) / (1 - 0,12)) =
    # 4% de 250,0 = 10,0. Custo da operação = 200 + 10 + 10,0 = 220,0;
    # impostos/taxas = 10; margem (40% de 220,0, só do custo da
    # operação) = 88,0; frete antes do ICMS = 230,0 + 88,0 = 318,0;
    # ICMS 12% gross-up: 318,0 / 0,88 = 361,36; valor_icms = 361,36 -
    # 318,0 = 43,36.
    parametros.aliquotas_icms.append(fs.AliquotaIcms(estado_origem="SP", estado_destino="RJ", aliquota=12.0))
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        cidade_origem="São Paulo, SP, Brasil", cidade_destino="Rio de Janeiro, RJ, Brasil",
    )
    calc = resultado["calculos_intermediarios"]
    assert calc["aliquota_icms_pct"] == pytest.approx(12.0)
    assert calc["valor_margem_lucro"] == pytest.approx(88.0, abs=0.01)  # 220,0 * 0.40
    assert calc["frete_sem_icms"] == pytest.approx(318.0, abs=0.01)  # já com a margem
    assert calc["valor_icms"] == pytest.approx(43.36, abs=0.01)  # gross-up: 318,0 / 0,88 - 318,0
    assert resultado["resultado"]["frete_total"] == pytest.approx(361.36, abs=0.01)


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


def test_aliquota_icms_nao_aplicada_quando_uf_nao_resolvivel(parametros):
    # endereço sem nenhuma UF identificável (nem sigla de filial cadastrada,
    # nem no texto) -- _uf_de_origem_ou_destino devolve "" e a função
    # desiste sem levantar erro nenhum, só não aplica ICMS.
    parametros.aliquotas_icms.append(fs.AliquotaIcms(estado_origem="*", estado_destino="*", aliquota=18.0))
    achada = fs.aliquota_icms_aplicavel(parametros, "endereço sem UF nenhuma", "Rio de Janeiro, RJ, Brasil")
    assert achada is None


def test_icms_aliquota_de_100_por_cento_gera_erro_de_configuracao(parametros):
    # ICMS é gross-up ("por dentro") -- uma alíquota de 100% causaria
    # divisão por zero (frete_sem_icms / (1 - 1.0)), por isso é rejeitada
    # antes de chegar lá.
    parametros.aliquotas_icms.append(fs.AliquotaIcms(estado_origem="SP", estado_destino="RJ", aliquota=100.0))
    with pytest.raises(fs.FreteConfigError, match="ICMS"):
        fs.calcular_orcamento(
            peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
            categoria="Geral", transporte="Rodoviário", sla="Padrão",
            cidade_origem="São Paulo, SP, Brasil", cidade_destino="Rio de Janeiro, RJ, Brasil",
        )


def test_pis_cofins_aplica_percentual_simples_no_frete_total(parametros):
    # PIS/COFINS é um percentual simples somado por fora sobre o
    # frete_sem_pis_cofins (229,61 de custo da operação -- 210 +
    # pedagio=9,61 de fallback, que já prevê PIS/COFINS 9,25% sobre
    # frete+custos+taxas: 220 * 1,0925 * 4% = 9,614 -> 9,61, ver
    # _pedagio_aplicado -- + impostos e taxas, ainda sem margem de
    # lucro), não gross-up "por dentro". A margem de lucro (40% padrão)
    # entra só depois, com valor em R$ calculado só sobre o custo da
    # operação (219,61), não sobre esse valor já com o imposto embutido.
    parametros.aliquota_pis_cofins = 9.25
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        cidade_origem="São Paulo, SP, Brasil", cidade_destino="Curitiba, PR, Brasil",
    )
    calc = resultado["calculos_intermediarios"]
    esperado = 229.61 * 1.0925
    assert calc["pedagio"] == pytest.approx(9.61, abs=0.01)
    assert calc["frete_sem_pis_cofins"] == pytest.approx(229.61, abs=0.01)
    assert calc["aliquota_pis_cofins_pct"] == pytest.approx(9.25)
    assert calc["valor_pis_cofins"] == pytest.approx(esperado - 229.61, abs=0.01)
    assert calc["frete_sem_margem_lucro"] == pytest.approx(esperado, abs=0.01)
    assert calc["valor_margem_lucro"] == pytest.approx(87.84, abs=0.01)  # 219,61 * 0.40
    assert resultado["resultado"]["frete_total"] == pytest.approx(esperado + 87.84, abs=0.01)


def test_pis_cofins_depois_margem_depois_icms_nessa_ordem(parametros):
    # Ordem fixa: PIS/COFINS primeiro (percentual simples sobre o custo
    # da operação + impostos e taxas), a margem de lucro em seguida
    # (valor calculado só sobre o custo da operação), e o ICMS por
    # último -- gross-up "por dentro" sobre o frete total já com a
    # margem embutida, não sobre o custo intermediário antes do lucro.
    # O pedágio de fallback (4%, ver _pedagio_aplicado) já prevê
    # PIS/COFINS 9,25% simples e ICMS 12% gross-up sobre
    # frete+custos+taxas: (220 * 1,0925) / 0,88 * 4% = 10,93.
    parametros.aliquota_pis_cofins = 9.25
    parametros.aliquotas_icms.append(fs.AliquotaIcms(estado_origem="SP", estado_destino="RJ", aliquota=12.0))
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        cidade_origem="São Paulo, SP, Brasil", cidade_destino="Rio de Janeiro, RJ, Brasil",
    )
    calc = resultado["calculos_intermediarios"]
    frete_com_pis_cofins = 230.93 * 1.0925
    frete_com_margem = frete_com_pis_cofins + 88.37  # margem = 220,93 * 0.40 (custo operação com novo pedágio)
    icms_esperado = frete_com_margem / (1 - 0.12) - frete_com_margem
    assert calc["pedagio"] == pytest.approx(10.93, abs=0.01)
    assert calc["frete_sem_pis_cofins"] == pytest.approx(230.93, abs=0.01)
    assert calc["frete_sem_margem_lucro"] == pytest.approx(frete_com_pis_cofins, abs=0.01)
    assert calc["valor_margem_lucro"] == pytest.approx(88.37, abs=0.01)
    assert calc["frete_sem_icms"] == pytest.approx(frete_com_margem, abs=0.01)
    assert calc["valor_icms"] == pytest.approx(icms_esperado, abs=0.01)
    assert resultado["resultado"]["frete_total"] == pytest.approx(frete_com_margem + icms_esperado, abs=0.01)


def test_sem_aliquota_pis_cofins_frete_total_fica_igual(parametros):
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        cidade_origem="São Paulo, SP, Brasil", cidade_destino="Curitiba, PR, Brasil",
    )
    calc = resultado["calculos_intermediarios"]
    assert calc["aliquota_pis_cofins_pct"] == pytest.approx(0.0)
    assert calc["valor_pis_cofins"] == pytest.approx(0.0)
    assert resultado["resultado"]["frete_total"] == pytest.approx(320.32)  # ver test_calculo_basico_sem_coleta


def test_sem_aliquota_cadastrada_frete_total_fica_igual(parametros):
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        cidade_origem="São Paulo, SP, Brasil", cidade_destino="Curitiba, PR, Brasil",
    )
    calc = resultado["calculos_intermediarios"]
    assert calc["aliquota_icms_pct"] == pytest.approx(0.0)
    assert calc["valor_icms"] == pytest.approx(0.0)
    assert resultado["resultado"]["frete_total"] == pytest.approx(320.32)  # ver test_calculo_basico_sem_coleta


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


def test_transporte_invalido_gera_erro_com_opcoes(parametros):
    with pytest.raises(fs.FreteInputError, match="Rodoviário"):
        fs.calcular_orcamento(
            peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=100,
            categoria="Geral", transporte="Transporte Inexistente", sla="Padrão",
        )


def test_sla_invalido_gera_erro_com_opcoes(parametros):
    with pytest.raises(fs.FreteInputError, match="Padrão"):
        fs.calcular_orcamento(
            peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=100,
            categoria="Geral", transporte="Rodoviário", sla="SLA Inexistente",
        )


def test_buscar_filial_invalida_gera_erro_com_opcoes(parametros):
    with pytest.raises(fs.FreteInputError, match="SP"):
        parametros.buscar_filial("Filial Que Não Existe")


def test_buscar_veiculo_por_peso_abaixo_da_menor_faixa_gera_erro():
    p = fs.ParametrosFrete()
    p.veiculos = {
        "vuc": fs.Veiculo(nome="VUC", de=500, ate=1000, tarifa_km=2.0, valor_tonelada_excedente=1.0),
    }
    p.veiculos_por_peso = sorted(p.veiculos.values(), key=lambda v: v.de)
    with pytest.raises(fs.FreteInputError, match="abaixo da menor faixa"):
        p.buscar_veiculo_por_peso(100)


def test_buscar_veiculo_por_peso_e_volume_sem_volume_nao_verifica_capacidade(parametros):
    # volume_total_m3 <= 0 (chamador não informou paletes com dimensão) --
    # não faz sentido checar capacidade, devolve o veículo escolhido só
    # pelo peso mesmo que ele não tenha capacidade_m3 cadastrada pra caber
    # qualquer coisa.
    escolhido = parametros.buscar_veiculo_por_peso_e_volume(peso_considerado=50, volume_total_m3=0)
    assert escolhido.nome == "VUC"


def test_buscar_faixa_coleta_abaixo_da_menor_faixa_gera_erro():
    p = fs.ParametrosFrete()
    p.faixas_coleta = [fs.FaixaDistancia(de=50, ate=999999, taxa_fixa=20, tarifa_km=0.3)]
    with pytest.raises(fs.FreteInputError, match="abaixo da menor faixa"):
        p.buscar_faixa_coleta(10)


def test_buscar_faixa_peso_fracionado_abaixo_da_menor_faixa_gera_erro():
    p = fs.ParametrosFrete()
    p.faixas_peso_fracionado = [fs.FaixaPeso(de=100, ate=999999, tarifa_base=50, custo_kg_adicional=1)]
    with pytest.raises(fs.FreteInputError, match="abaixo da menor faixa de peso do Fracionado"):
        p.buscar_faixa_peso_fracionado(10)


def test_buscar_faixa_distancia_fracionado_abaixo_da_menor_faixa_gera_erro():
    p = fs.ParametrosFrete()
    p.faixas_distancia_fracionado = [fs.FaixaDistancia(de=100, ate=999999, taxa_fixa=20, tarifa_km=0.3)]
    with pytest.raises(fs.FreteInputError, match="abaixo da menor faixa de distância do Fracionado"):
        p.buscar_faixa_distancia_fracionado(10)


def test_buscar_coleta_cidade_fixa_outros_veiculos_ignora_filial_diferente(parametros):
    parametros.coleta_cidades_fixas = [
        fs.ColetaCidadeFixa(filial_origem="RJ", cidade_destino="Niterói", veiculo="Truck", valor_fixo=80.0),
    ]
    achados = parametros.buscar_coleta_cidade_fixa_outros_veiculos("SP", "Niterói", "VUC")
    assert achados == []  # linha cadastrada é de outra filial (RJ != SP)


def test_buscar_coleta_cidade_fixa_outros_veiculos_ignora_o_proprio_veiculo(parametros):
    parametros.coleta_cidades_fixas = [
        fs.ColetaCidadeFixa(filial_origem="SP", cidade_destino="Niterói", veiculo="VUC", valor_fixo=80.0),
    ]
    achados = parametros.buscar_coleta_cidade_fixa_outros_veiculos("SP", "Niterói", "VUC")
    assert achados == []  # só tem o próprio veículo cadastrado, não é "outro"


def test_uf_de_origem_ou_destino_vazio_quando_texto_ausente(parametros):
    assert fs._uf_de_origem_ou_destino(parametros, None) == ""
    assert fs._uf_de_origem_ou_destino(parametros, "") == ""


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


# ============================================================
# _campo_bate_localidade / _especificidade_localidade /
# _normalizar_par_cidades -- helpers compartilhados por taxa de balsa,
# prioridade de rota, distância fixa e pedágio por rota.
# ============================================================


def test_campo_bate_localidade_curinga_bate_com_qualquer_coisa():
    assert fs._campo_bate_localidade("*", "qualquer cidade", "SP") is True
    assert fs._campo_bate_localidade("*", "", "") is True


def test_campo_bate_localidade_sigla_uf_exige_uf_resolvida():
    assert fs._campo_bate_localidade("sp", "campinas", "sp") is True
    # UF vazia (não resolvida) nunca bate, mesmo cadastrado sendo uma UF
    assert fs._campo_bate_localidade("sp", "campinas", "") is False


def test_campo_bate_localidade_nome_exato_de_cidade():
    assert fs._campo_bate_localidade("manaus", "manaus", "am") is True
    assert fs._campo_bate_localidade("manaus", "belem", "pa") is False


def test_especificidade_localidade_curinga_menos_especifico_que_uf_e_cidade():
    assert fs._especificidade_localidade("*") == 0
    assert fs._especificidade_localidade("sp") == 1  # sigla de UF
    assert fs._especificidade_localidade("campinas") == 2  # nome de cidade


def test_normalizar_par_cidades_none_quando_algum_lado_vazio():
    assert fs._normalizar_par_cidades("", "Belém, PA, Brasil") is None
    assert fs._normalizar_par_cidades("Campinas", "") is None
    assert fs._normalizar_par_cidades(None, "Belém, PA, Brasil") is None


def test_normalizar_par_cidades_none_quando_cidade_nao_identificavel():
    # string não vazia, mas sem nenhum segmento de verdade depois de
    # dividir por vírgula e remover espaços -- _cidade_da_retirada não
    # consegue extrair nenhuma cidade dali.
    assert fs._normalizar_par_cidades(" , , ", "Belém, PA, Brasil") is None


def test_normalizar_par_cidades_sucesso():
    resultado = fs._normalizar_par_cidades("Campinas", "Belém, Pará, Brasil")
    assert resultado == ("campinas", "belem", "pa")


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


def test_pedagio_rota_ignora_praca_id_pendurado_sem_cadastro(parametros):
    # pedagios_rota referencia um praca_id que não existe mais em
    # pracas_pedagio (ex: praça excluída, mas o vínculo ficou órfão) --
    # não pode quebrar a soma, só ignora essa praça.
    parametros.pracas_pedagio = {1: fs.PracaPedagio(1, "Praça 5", "BR-101", "ViaSul", {2: 12.4})}
    parametros.pedagios_rota = [
        fs.PedagioRota("Curitiba", "Florianópolis", 1),
        fs.PedagioRota("Curitiba", "Florianópolis", 999),  # praca_id órfão
    ]
    total, pracas = fs.pedagio_rota_aplicavel(parametros, "Curitiba, PR, Brasil", "Florianópolis, SC, Brasil", 2)
    assert total == pytest.approx(12.4)
    assert pracas == ["Praça 5"]


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


def test_pedagio_aplicado_usa_valor_informado_quando_ha_praca_cadastrada(parametros):
    # Com praça cadastrada pro corredor + eixos do veículo, o pedágio
    # informado (pré-preenchido na busca de distância a partir dessa
    # praça, editável) prevalece -- não entra o fallback de 4%.
    parametros.veiculos["vuc"].numero_eixos = 2
    parametros.pracas_pedagio = {1: fs.PracaPedagio(1, "Praça 5", "BR-101", "ViaSul", {2: 50.0})}
    parametros.pedagios_rota = [fs.PedagioRota("São Paulo", "Curitiba", 1)]
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        cidade_origem="São Paulo, SP, Brasil", cidade_destino="Curitiba, PR, Brasil",
        pedagio=99.0,
    )
    calc = resultado["calculos_intermediarios"]
    assert calc["pedagio"] == pytest.approx(99.0)
    assert calc["pedagio_estimado_pct"] is None
    assert calc["pedagio_pracas"] == ["Praça 5"]


def test_pedagio_aplicado_cai_no_fallback_de_4_por_cento_sem_praca_cadastrada(parametros):
    # Sem corredor de pedágio cadastrado pra rota, ignora o valor
    # informado (estimativa genérica do Google Maps, ou manual) e aplica
    # PEDAGIO_PCT_FALLBACK (4%) sobre frete + custos operacionais + taxas
    # (com PIS/COFINS e ICMS previstos por cima, sem margem -- ambos 0%
    # aqui): 4% de (frete_ajustado=200 + custo_manutencao=10 +
    # custo_taxas_adicionais=10) = 4% de 220 = 8,8.
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        cidade_origem="São Paulo, SP, Brasil", cidade_destino="Curitiba, PR, Brasil",
        pedagio=99.0,
    )
    calc = resultado["calculos_intermediarios"]
    assert calc["frete_ajustado"] == pytest.approx(200.0)
    assert calc["pedagio"] == pytest.approx(8.8)  # 220 * 4%
    assert calc["pedagio_estimado_pct"] == pytest.approx(4.0)
    assert calc["pedagio_pracas"] is None


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


def test_distancia_balsa_km_rota_direta(parametros):
    parametros.distancias_fixas = [fs.DistanciaFixa("Belém", "Manaus", 2096)]
    km = fs.distancia_balsa_km(parametros, "Belém, Pará, Brasil", "Manaus, Amazonas, Brasil", prioridade_rota=None)
    assert km == 2096


def test_distancia_balsa_km_via_prioridade_de_rota(parametros):
    # Com escala obrigatória (prioridade_rota = nome da filial), a
    # distância fixa é checada na perna filial->destino, não na rota
    # origem->destino inteira (que nem bateria: São Paulo -> Manaus não
    # tem corredor cadastrado).
    parametros.distancias_fixas = [fs.DistanciaFixa("Belém", "Manaus", 2096)]
    km = fs.distancia_balsa_km(
        parametros, "São Paulo, SP, Brasil", "Manaus, Amazonas, Brasil", prioridade_rota="Belém",
    )
    assert km == 2096


def test_distancia_balsa_km_sem_corredor_cadastrado(parametros):
    km = fs.distancia_balsa_km(parametros, "São Paulo, SP, Brasil", "Curitiba, PR, Brasil", prioridade_rota=None)
    assert km == 0.0


def test_calcular_orcamento_nao_cobra_tarifa_de_estrada_na_travessia_de_balsa(parametros):
    # Cenário do bug relatado: distância total Belém->Manaus é 2096 km,
    # todos com travessia de balsa (sem corredor rodoviário) -- a tarifa
    # por km do veículo (rodoviária) não pode incidir sobre nenhum desses
    # km, só a taxa de balsa (fixa, já cadastrada em taxas_balsa) entra na
    # conta. Sem a correção, custo_km cobraria a viagem inteira como se
    # fosse rodovia, dobrando a cobrança da travessia.
    parametros.distancias_fixas = [fs.DistanciaFixa("Belém", "Manaus", 2096)]
    parametros.taxas_balsa = [
        fs.TaxaBalsa(cidade_origem="*", cidade_destino="Manaus", veiculo="VUC", tipo="fixo", valor=7110.58),
    ]
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=2096, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        cidade_origem="Belém, Pará, Brasil", cidade_destino="Manaus, Amazonas, Brasil",
    )
    calc = resultado["calculos_intermediarios"]
    assert calc["distancia_balsa_km"] == 2096
    assert calc["distancia_faturavel_km"] == 0
    assert calc["custo_km"] == pytest.approx(0.0)
    assert calc["custo_balsa"] == pytest.approx(7110.58)
    # Balsa é custo de transporte de verdade (a travessia é parte do
    # trajeto), não um "imposto" -- entra em total_custo_operacao, não em
    # total_impostos_taxas. O pedágio cai no fallback de 4%, e a base
    # agora inclui a balsa + as taxas (GRIS 1% de 1000=10, e a taxa
    # regional de Manaus, fixa em 50): 4% de (7110,58 + 10 + 50) = 286,82
    # (ver _pedagio_aplicado). Custo da operação = 7110,58 + 286,82 =
    # 7397,4. A margem de lucro (40%) incide por cima desse total: 40% de
    # 7397,4 = 2958,96.
    assert calc["total_custo_operacao"] == pytest.approx(7397.4)
    assert calc["custo_taxas_adicionais"] == pytest.approx(10.0)
    assert calc["valor_margem_lucro"] == pytest.approx(2958.96, abs=0.01)


def test_calcular_orcamento_cobra_so_a_perna_rodoviaria_quando_ha_escala_por_balsa(parametros):
    # Origem fora do Pará: a perna origem->Belém continua rodoviária
    # (cobrada por km normalmente), só a perna Belém->Manaus (balsa) sai
    # do cálculo de custo_km/manutenção -- distancia aqui já vem somada
    # (como faria geo_service.calcular_distancia): 900 km de estrada até
    # Belém + 2096 km de balsa até Manaus = 2996 km.
    parametros.distancias_fixas = [fs.DistanciaFixa("Belém", "Manaus", 2096)]
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=2996, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        cidade_origem="São Paulo, SP, Brasil", cidade_destino="Manaus, Amazonas, Brasil",
        prioridade_rota="Belém",
    )
    calc = resultado["calculos_intermediarios"]
    assert calc["distancia_balsa_km"] == 2096
    assert calc["distancia_faturavel_km"] == 900
    assert calc["custo_km"] == pytest.approx(900 * 2.0)  # tarifa_km do VUC no fixture = 2.0


def test_calcular_orcamento_sem_corredor_de_balsa_cobra_distancia_inteira(parametros):
    # Sem nenhuma distância fixa cadastrada pra essa rota, comportamento
    # de sempre: tarifa por km incide sobre a distância inteira.
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=300, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
        cidade_origem="São Paulo, SP, Brasil", cidade_destino="Curitiba, PR, Brasil",
    )
    calc = resultado["calculos_intermediarios"]
    assert calc["distancia_balsa_km"] == 0
    assert calc["distancia_faturavel_km"] == 300
    assert calc["custo_km"] == pytest.approx(300 * 2.0)


# ============================================================
# calcular_orcamento -- validação de entrada (cada campo isoladamente)
# ============================================================


def _orcamento_base(**overrides):
    base = dict(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
    )
    base.update(overrides)
    return base


@pytest.mark.parametrize("overrides,mensagem", [
    ({"distancia_coleta": -1}, "coleta"),
    ({"valor_mercadoria": -1}, "mercadoria"),
    ({"valor_coleta_terceirizada": -1}, "coleta terceirizada"),
    ({"valor_entrega_terceirizada": -1}, "entrega terceirizada"),
    ({"pedagio": -1}, "pedágio"),
    ({"distancia_retorno": -1}, "retorno"),
])
def test_calcular_orcamento_rejeita_campo_negativo_ou_fora_do_intervalo(parametros, overrides, mensagem):
    with pytest.raises(fs.FreteInputError, match=mensagem):
        fs.calcular_orcamento(**_orcamento_base(**overrides))


def test_calcular_orcamento_palete_com_dimensao_invalida(parametros):
    with pytest.raises(fs.FreteInputError, match="Comprimento"):
        fs.calcular_orcamento(**_orcamento_base(paletes=[{"comprimento": 0, "largura": 30, "altura": 25}]))


def test_calcular_orcamento_custo_extra_categoria_invalida(parametros):
    with pytest.raises(fs.FreteInputError, match="Categoria de custo extra"):
        fs.calcular_orcamento(**_orcamento_base(
            custos_extras=[{"categoria": "Categoria Inexistente", "valor": 10}],
        ))


def test_calcular_orcamento_custo_extra_valor_negativo(parametros):
    with pytest.raises(fs.FreteInputError, match="custo extra"):
        fs.calcular_orcamento(**_orcamento_base(
            custos_extras=[{"categoria": "Paletização", "valor": -10}],
        ))


def test_upgrade_de_veiculo_por_volume_passa_pelo_veiculo_inicial_ate_achar_um_que_caiba(parametros):
    # fator_cubagem baixo o bastante pra não empurrar o peso considerado
    # pra fora da faixa do VUC (que continua sendo escolhido por peso),
    # mas o volume em si (9 m³) não cabe na capacidade útil do VUC (8 m³)
    # -- precisa subir pro Truck (24 m³ útil), passando pelo laço de
    # "veículos maiores" em vez de já vir certo de cara (diferente de
    # test_upgrade_de_veiculo_por_volume, onde o fator_cubagem alto já
    # escolhe o veículo maior direto pelo peso cubado).
    parametros.transportes["baixacubagem"] = fs.Transporte("BaixaCubagem", 1.0, fator_cubagem=10)
    paletes = _paletes(comprimento=300, largura=300, altura=100)  # 9 m³
    resultado = fs.calcular_orcamento(
        peso=50, paletes=paletes, distancia=10, valor_mercadoria=100,
        categoria="Geral", transporte="BaixaCubagem", sla="Padrão",
    )
    assert resultado["entrada"]["veiculo"] == "Truck"


# ============================================================
# calcular_orcamento_fracionado -- validação de entrada e faixas
# ============================================================


def _fracionado_base(**overrides):
    base = dict(
        peso=80, paletes=_paletes(), distancia=350, valor_mercadoria=1200,
        categoria="Geral", transporte="Rodoviário", sla="Padrão", veiculo="VUC",
    )
    base.update(overrides)
    return base


@pytest.mark.parametrize("overrides,mensagem", [
    ({"peso": 0}, "Peso"),
    ({"paletes": []}, "palete"),
    ({"distancia": 0}, "Distância"),
    ({"valor_mercadoria": -1}, "mercadoria"),
    ({"pedagio": -1}, "pedágio"),
])
def test_calcular_orcamento_fracionado_rejeita_campo_invalido(parametros, overrides, mensagem):
    with pytest.raises(fs.FreteInputError, match=mensagem):
        fs.calcular_orcamento_fracionado(**_fracionado_base(**overrides))


def test_calcular_orcamento_fracionado_palete_com_dimensao_invalida(parametros):
    with pytest.raises(fs.FreteInputError, match="Comprimento"):
        fs.calcular_orcamento_fracionado(**_fracionado_base(
            paletes=[{"comprimento": 0, "largura": 30, "altura": 25}],
        ))


def test_calcular_orcamento_fracionado_custo_extra_categoria_invalida(parametros):
    with pytest.raises(fs.FreteInputError, match="Categoria de custo extra"):
        fs.calcular_orcamento_fracionado(**_fracionado_base(
            custos_extras=[{"categoria": "Categoria Inexistente", "valor": 10}],
        ))


def test_calcular_orcamento_fracionado_custo_extra_valor_negativo(parametros):
    with pytest.raises(fs.FreteInputError, match="negativo"):
        fs.calcular_orcamento_fracionado(**_fracionado_base(
            custos_extras=[{"categoria": "Diversos", "valor": -10.0}],
        ))


def test_calcular_orcamento_fracionado_quantidade_do_palete_menor_que_1(parametros):
    with pytest.raises(fs.FreteInputError, match="quantidade"):
        fs.calcular_orcamento_fracionado(**_fracionado_base(
            paletes=[{"comprimento": 40, "largura": 30, "altura": 25, "quantidade": 0}],
        ))


# ============================================================
# calcular_orcamento_fracionado -- prazo por destino (prazo_fracionado_
# destino) substitui a fórmula por km quando a rota está cadastrada
# (achado da investigação do prazo real do Fracionado, ver CONTEXTO.md:
# diferente da Lotação, o prazo real do Fracionado não varia com km
# rodado, varia com UF+capital/interior do destino).
# ============================================================


def _com_faixas_fracionado_genericas(p):
    # Faixa de peso/distância genérica só pra calcular_orcamento_fracionado
    # completar (frete_base) sem custos_fracionado_destino cadastrado --
    # os testes desta seção só se importam com o prazo, não com o valor
    # do frete em si.
    p.faixas_peso_fracionado = [fs.FaixaPeso(de=0, ate=999999, tarifa_base=50, custo_kg_adicional=0)]
    p.faixas_distancia_fracionado = [fs.FaixaDistancia(de=0, ate=999999, taxa_fixa=20, tarifa_km=0.3)]


def test_prazo_fracionado_usa_tabela_por_destino_quando_cadastrada(parametros):
    # distancia bem alta pra deixar claro que, se a fórmula por km fosse
    # usada, o resultado seria bem diferente de 9 -- confirma que a
    # tabela tem prioridade sobre _prazo_estimado_dias_uteis.
    _com_faixas_fracionado_genericas(parametros)
    parametros.prazo_fracionado_destino = {("SP", "PA", "CAPITAL"): 9}
    resultado = fs.calcular_orcamento_fracionado(**_fracionado_base(
        distancia=3000,
        cidade_origem="São Paulo, SP, Brasil", cidade_destino="Belém, PA, Brasil",
    ))
    assert resultado["resultado"]["prazo_estimado_dias_uteis"] == 9


def test_prazo_fracionado_cai_no_fallback_por_km_sem_tabela_cadastrada(parametros):
    # parametros de teste não populam prazo_fracionado_destino -- sem
    # entrada pra essa rota, usa a mesma fórmula da Lotação (1 dia + 1 a
    # cada 500km, sem balsa aqui).
    _com_faixas_fracionado_genericas(parametros)
    resultado = fs.calcular_orcamento_fracionado(**_fracionado_base(
        distancia=1200,
        cidade_origem="São Paulo, SP, Brasil", cidade_destino="Belém, PA, Brasil",
    ))
    assert resultado["resultado"]["prazo_estimado_dias_uteis"] == 3  # 1 + 1200//500


def test_prazo_fracionado_sem_cidade_cai_no_fallback_por_km(parametros):
    # Sem cidade_origem/cidade_destino (ex: formulário antigo que não
    # manda essa informação) não dá pra classificar UF/capital-interior
    # -- cai no fallback por km direto, sem erro.
    _com_faixas_fracionado_genericas(parametros)
    resultado = fs.calcular_orcamento_fracionado(**_fracionado_base(distancia=1200))
    assert resultado["resultado"]["prazo_estimado_dias_uteis"] == 3


def test_prazo_fracionado_bahia_interior_usa_interior_i_como_aproximacao(parametros):
    # Mesma aproximação de _custo_fracionado_destino_aplicavel: a Bahia
    # tem 3 faixas na planilha (CAPITAL/INTERIOR I/INTERIOR II), mas
    # _classificar_capital_interior só distingue CAPITAL x INTERIOR --
    # cidades do interior caem em "INTERIOR" e tentam "INTERIOR I" como
    # variante antes de cair no fallback por km.
    _com_faixas_fracionado_genericas(parametros)
    parametros.prazo_fracionado_destino = {("SP", "BA", "INTERIOR I"): 8}
    resultado = fs.calcular_orcamento_fracionado(**_fracionado_base(
        distancia=1800,
        cidade_origem="São Paulo, SP, Brasil", cidade_destino="Ilhéus, BA, Brasil",
    ))
    assert resultado["resultado"]["prazo_estimado_dias_uteis"] == 8


# ============================================================
# RCA -- taxa digitável por orçamento igual GRIS/Ad Valorem (ver
# _NOME_TAXA_RCA), mas só existe no Fracionado (manual de precificação):
# calcular_orcamento (Lotação) nunca aplica RCA, mesmo que esteja
# cadastrado em taxas_adicionais.
# ============================================================


def test_rca_digitado_substitui_o_cadastrado_no_fracionado(parametros):
    _com_faixas_fracionado_genericas(parametros)
    parametros.taxas_adicionais.append(fs.TaxaAdicional(nome="RCA", tipo="percentual", valor=0.12))
    resultado = fs.calcular_orcamento_fracionado(**_fracionado_base(rca_pct=5.0, valor_mercadoria=1000))
    calc = resultado["calculos_intermediarios"]
    rca = next(t for t in calc["taxas_adicionais"] if t["nome"] == "RCA")
    assert rca["valor_configurado"] == pytest.approx(5.0)
    assert rca["valor_aplicado"] == pytest.approx(50.0)  # 1000 * 5%


def test_rca_digitado_abaixo_do_cadastrado_gera_erro_no_fracionado(parametros):
    _com_faixas_fracionado_genericas(parametros)
    parametros.taxas_adicionais.append(fs.TaxaAdicional(nome="RCA", tipo="percentual", valor=0.12))
    with pytest.raises(fs.FreteInputError, match="RCA"):
        fs.calcular_orcamento_fracionado(**_fracionado_base(rca_pct=0.05))


def test_rca_nao_informado_usa_cadastrado_no_fracionado(parametros):
    _com_faixas_fracionado_genericas(parametros)
    parametros.taxas_adicionais.append(fs.TaxaAdicional(nome="RCA", tipo="percentual", valor=0.12))
    resultado = fs.calcular_orcamento_fracionado(**_fracionado_base(valor_mercadoria=1000))
    calc = resultado["calculos_intermediarios"]
    rca = next(t for t in calc["taxas_adicionais"] if t["nome"] == "RCA")
    assert rca["valor_configurado"] == pytest.approx(0.12)
    assert rca["valor_aplicado"] == pytest.approx(1.2)  # 1000 * 0.12%


def test_rca_nunca_aplica_na_lotacao_mesmo_cadastrado(parametros):
    # RCA cadastrado em taxas_adicionais (ex: alguém cadastrou pensando só
    # no Fracionado) não deve aparecer no cálculo de Lotação de jeito
    # nenhum -- incluir_rca=False é o padrão de calcular_orcamento.
    parametros.taxas_adicionais.append(fs.TaxaAdicional(nome="RCA", tipo="percentual", valor=0.12))
    resultado = fs.calcular_orcamento(
        peso=50, paletes=_paletes(), distancia=100, valor_mercadoria=1000,
        categoria="Geral", transporte="Rodoviário", sla="Padrão",
    )
    calc = resultado["calculos_intermediarios"]
    assert "RCA" not in [t["nome"] for t in calc["taxas_adicionais"]]


def test_buscar_faixa_peso_fracionado_sem_cadastro_da_erro_de_configuracao(parametros):
    # parametros de teste (ver _parametros_teste) não populam faixas do
    # Fracionado -- diferente das outras tabelas, essas têm falha
    # tolerada no carregamento (ver ParametrosFrete.load), só quebra
    # quando alguém de fato tenta cotar um Fracionado.
    with pytest.raises(fs.FreteConfigError, match="Fracionado"):
        parametros.buscar_faixa_peso_fracionado(100)


def test_buscar_faixa_distancia_fracionado_sem_cadastro_da_erro_de_configuracao(parametros):
    with pytest.raises(fs.FreteConfigError, match="Fracionado"):
        parametros.buscar_faixa_distancia_fracionado(100)


# ============================================================
# ParametrosFrete.load() -- validação de configuração mínima no banco
# (diferente dos testes acima, que usam parametros montados em memória,
# aqui carrega de verdade do banco_temporario pra exercitar os "Nenhum(a)
# ... cadastrado" de load(), disparados quando uma tabela obrigatória
# fica vazia).
# ============================================================


@pytest.mark.parametrize("tabela,mensagem", [
    ("veiculos", "Nenhum veículo cadastrado"),
    ("faixas_coleta", "Nenhuma faixa de coleta cadastrada"),
    ("categorias", "Nenhuma categoria cadastrada"),
    ("transportes", "Nenhum transporte cadastrado"),
    ("slas", "Nenhum SLA cadastrado"),
    ("filiais", "Nenhuma filial cadastrada"),
])
def test_parametros_load_falha_quando_tabela_obrigatoria_fica_vazia(banco_temporario, tabela, mensagem):
    with db.get_connection() as conn:
        conn.execute(f"DELETE FROM {tabela}")
    with pytest.raises(fs.FreteConfigError, match=mensagem):
        fs.ParametrosFrete().load()
