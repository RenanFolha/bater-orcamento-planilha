"""Ferramenta de desenvolvimento (NÃO é teste automatizado de regressão /
pytest) para comparar, campo a campo, o orçamento calculado pelo sistema
(frete_service.py, usando os parâmetros JÁ cadastrados hoje em frete.db)
contra os valores reais históricos da planilha legada
"Planilhas/COTAÇÃO SSONIC - 2026.xlsx" (aba "Base Geral").

Os casos abaixo em CASOS foram extraídos manualmente dessa planilha
(linhas com STATUS CUSTO = "CUSTO OK", ou seja, cotações fechadas) nos
modais que o sistema cobre hoje: "LTL - FRACIONADO (SP)" (-> frete
fracionado) e "FTL - LOTAÇÃO (AM)" (-> frete por veículo/lotação). A
planilha usa modal aéreo também, que o sistema não cobre -- não incluído.

Limitações conhecidas dos casos (documentadas aqui para não serem
confundidas com bug do sistema):

- A planilha não registra o KM usado no cálculo de custo -- o custo lá
  vem só de uma tabela por cidade/UF de destino, sem depender de
  distância. O sistema, ao contrário, PRECISA de uma distância em km
  (tarifa_km do veículo / faixa de distância do fracionado). As
  distâncias abaixo em "distancia_km" são estimativas grosseiras
  (rodoviário aproximado, de memória) só para dar ao sistema um input
  válido -- não vieram da planilha e não devem ser tratadas como
  precisas. Isso por si só já é motivo de uma parcela do frete base não
  bater (ver item 6 do relatório de divergências).
- A planilha não tem dimensões de palete (comprimento/largura/altura),
  só M² e PESO CUBADO já calculados. Para não inventar dimensões
  arbitrárias, cada caso usa um único "palete sintético" cúbico cujo
  volume (comprimento × largura × altura, em cm) reproduz exatamente o
  M³ que a própria planilha já calculou para aquela linha (ver
  _palete_sintetico abaixo) -- assim peso_cubado/peso_considerado saem
  iguais aos da planilha, independente do shape real da carga.
- Categoria/Transporte/SLA não existem na planilha -- usamos o
  transporte "Rodoviário" (fator_cubagem 300, igual ao usado pela
  planilha nas fórmulas de peso cubado) e a categoria/SLA mais neutros
  cadastrados (multiplicador 1.0), lidos direto do banco em vez de
  hardcoded (ver _parametros_neutros) para não depender de digitar
  acento certo.
- GRIS e Ad Valorem cadastrados no sistema são um % único nacional
  (Tabela de Preços), enquanto na planilha variam por cidade/UF de
  destino -- a divergência nesses dois campos é esperada e não é bug de
  fórmula, é falta de dados (ver relatório de divergências, item 3).
- Para o modal Fracionado, não há nenhuma faixa de peso cadastrada em
  Tabela de Preços → Fracionado hoje (tabela faixas_peso vazia para
  tipo_frete='Fracionado') -- os casos LTL abaixo vão falhar com
  FreteConfigError até que isso seja cadastrado. O script reporta esse
  erro no lugar do resultado e segue para os próximos casos.

Como rodar (sempre pela raiz do repo, usando o Python do venv):

    .venv/Scripts/python.exe comparar_planilha.py              # todos os casos
    .venv/Scripts/python.exe comparar_planilha.py lotacao       # só lotação (FTL)
    .venv/Scripts/python.exe comparar_planilha.py fracionado    # só fracionado (LTL)

Rode de novo a cada ajuste no motor de cálculo (frete_service.py) ou nos
dados cadastrados (frete.db) para acompanhar se os valores vão se
aproximando dos da planilha.
"""
import sys

import frete_db as db
import frete_service as fs

sys.stdout.reconfigure(encoding="utf-8")

CAMINHO_PLANILHA = "Planilhas/COTAÇÃO SSONIC - 2026.xlsx"

# Tolerância para considerar um campo "batendo" (%). Acima disso é reportado
# como divergência na tabela e conta no resumo final.
TOLERANCIA_PCT = 1.0


def _palete_sintetico(volume_m3: float) -> list[dict]:
    """Um palete cúbico (comprimento=largura=altura) cujo volume em m³
    reproduz volume_m3. Se a planilha não tiver m³ (FTL costuma não ter,
    o peso real já basta pra escolher o veículo), usa um volume pequeno
    fixo (1 m³) só para passar a validação de dimensões > 0 sem
    distorcer o peso considerado (fator_cubagem 300 -> peso cubado 300kg,
    tipicamente bem abaixo do peso real nesses casos)."""
    v = volume_m3 if volume_m3 and volume_m3 > 0 else 1.0
    lado_cm = (v * 1_000_000) ** (1 / 3)
    return [{"comprimento": lado_cm, "largura": lado_cm, "altura": lado_cm, "quantidade": 1}]


def _parametros_neutros() -> tuple[str, str, str]:
    """Nomes (exatos, do jeito que estão no banco) de um transporte
    Rodoviário, uma categoria e um SLA com multiplicador 1.0 -- lidos do
    banco em vez de hardcoded para não depender de acentuação digitada
    certa (frete_service compara nome.strip().lower())."""
    with db.get_connection() as conn:
        transporte = conn.execute(
            "SELECT nome FROM transportes WHERE fator_cubagem = 300 LIMIT 1"
        ).fetchone()
        categoria = conn.execute(
            "SELECT nome FROM categorias WHERE multiplicador = 1.0 ORDER BY id LIMIT 1"
        ).fetchone()
        sla = conn.execute(
            "SELECT nome FROM slas WHERE multiplicador = 1.0 ORDER BY id LIMIT 1"
        ).fetchone()
    if not (transporte and categoria and sla):
        raise RuntimeError(
            "Não achei transporte Rodoviário (fator_cubagem=300) / categoria / SLA "
            "com multiplicador 1.0 cadastrados em frete.db -- cadastre antes de rodar."
        )
    return transporte["nome"], categoria["nome"], sla["nome"]


# Cada caso: dados de entrada (iguais aos da planilha, mais a distância
# estimada e o palete sintético) + "esperado" (valores que a própria
# planilha calculou para aquela linha, colunas AH/AI/AJ/AK/AL/AM/AN/AO da
# aba "Base Geral").
CASOS = [
    {
        "nome": "LTL SP->Tucuruí/PA (linha 2)",
        "tipo": "fracionado",
        "peso": 130, "m3": 1.072526, "distancia_km": 2900,
        "valor_mercadoria": 213750,
        "cidade_origem": "São Paulo, SP", "cidade_destino": "Tucuruí, PA",
        "esperado": {
            "frete_base": 1043.73, "gris": 427.50, "ad_valorem": 1282.50,
            "taxa_fluvial": 0.0, "frete_sem_imposto": 2753.73, "pis_cofins": 0.0,
            "icms": 207.27, "frete_final": 2961.01,
        },
    },
    {
        "nome": "LTL SP->Moju/PA (linha 3)",
        "tipo": "fracionado",
        "peso": 140, "m3": 0.3, "distancia_km": 2850,
        "valor_mercadoria": 19723.73,
        "cidade_origem": "São Paulo, SP", "cidade_destino": "Moju, PA",
        "esperado": {
            "frete_base": 587.12, "gris": 39.45, "ad_valorem": 118.34,
            "taxa_fluvial": 0.0, "frete_sem_imposto": 744.91, "pis_cofins": 0.0,
            "icms": 56.07, "frete_final": 800.97,
        },
    },
    {
        "nome": "LTL SP->Manaus/AM peso 16kg (linha 4)",
        "tipo": "fracionado",
        "peso": 16, "m3": 0.25, "distancia_km": 3490,
        "valor_mercadoria": 1207.68,
        "cidade_origem": "São Paulo, SP", "cidade_destino": "Manaus, AM",
        "esperado": {
            "frete_base": 377.91, "gris": 2.42, "ad_valorem": 7.25,
            "taxa_fluvial": 12.08, "frete_sem_imposto": 399.65, "pis_cofins": 0.0,
            "icms": 30.08, "frete_final": 429.73,
        },
    },
    {
        "nome": "LTL SP->Manaus/AM peso 19kg (linha 5)",
        "tipo": "fracionado",
        "peso": 19, "m3": 0.3, "distancia_km": 3490,
        "valor_mercadoria": 721.2,
        "cidade_origem": "São Paulo, SP", "cidade_destino": "Manaus, AM",
        "esperado": {
            "frete_base": 377.91, "gris": 1.44, "ad_valorem": 4.33,
            "taxa_fluvial": 7.21, "frete_sem_imposto": 390.89, "pis_cofins": 0.0,
            "icms": 29.42, "frete_final": 420.31,
        },
    },
    {
        "nome": "LTL SP->Manaus/AM peso 270kg (linha 6)",
        "tipo": "fracionado",
        "peso": 270, "m3": 3.5, "distancia_km": 3490,
        "valor_mercadoria": 21900,
        "cidade_origem": "São Paulo, SP", "cidade_destino": "Manaus, AM",
        "esperado": {
            "frete_base": 2822.21, "gris": 43.80, "ad_valorem": 131.40,
            "taxa_fluvial": 219.0, "frete_sem_imposto": 3216.41, "pis_cofins": 0.0,
            "icms": 242.10, "frete_final": 3458.50,
        },
    },
    {
        "nome": "LTL SP->Manaus/AM peso 20,92kg (linha 7)",
        "tipo": "fracionado",
        "peso": 20.92, "m3": 0.062304, "distancia_km": 3490,
        "valor_mercadoria": 20000,
        "cidade_origem": "São Paulo, SP", "cidade_destino": "Manaus, AM",
        "esperado": {
            "frete_base": 204.37, "gris": 40.0, "ad_valorem": 120.0,
            "taxa_fluvial": 200.0, "frete_sem_imposto": 564.37, "pis_cofins": 0.0,
            "icms": 42.48, "frete_final": 606.85,
        },
    },
    {
        "nome": "FTL Manaus/AM->Macapá/AP (linha 10)",
        "tipo": "lotacao",
        "peso": 24000, "m3": 0, "distancia_km": 1500,
        "valor_mercadoria": 2132900,
        "cidade_origem": "Manaus, AM", "cidade_destino": "Macapá, AP",
        "esperado": {
            "frete_base": 20268.15, "gris": 1066.45, "ad_valorem": 5972.12,
            "taxa_fluvial": 0.0, "frete_sem_imposto": 27306.72, "pis_cofins": 0.0,
            "icms": 3723.64, "frete_final": 31030.37,
        },
    },
    {
        "nome": "FTL Manaus/AM->Tocantinópolis/TO (linha 42)",
        "tipo": "lotacao",
        "peso": 30000, "m3": 0, "distancia_km": 1700,
        "valor_mercadoria": 15000000,
        "cidade_origem": "Manaus, AM", "cidade_destino": "Tocantinópolis, TO",
        "esperado": {
            "frete_base": 17810.41, "gris": 0.0, "ad_valorem": 0.0,
            "taxa_fluvial": 0.0, "frete_sem_imposto": 17810.41, "pis_cofins": 0.0,
            "icms": 2428.69, "frete_final": 20239.10,
        },
    },
    {
        "nome": "FTL Manaus/AM->São Paulo/SP (linha 99)",
        "tipo": "lotacao",
        "peso": 8096, "m3": 0, "distancia_km": 3490,
        "valor_mercadoria": 228371,
        "cidade_origem": "Manaus, AM", "cidade_destino": "São Paulo, SP",
        "esperado": {
            "frete_base": 38611.44, "gris": 342.56, "ad_valorem": 799.30,
            "taxa_fluvial": 274.05, "frete_sem_imposto": 40027.34, "pis_cofins": 1200.82,
            "icms": 5458.27, "frete_final": 46686.43,
        },
    },
    {
        "nome": "FTL Manaus/AM->Santa Bárbara D'Oeste/SP (linha 100)",
        "tipo": "lotacao",
        "peso": 8096, "m3": 0, "distancia_km": 3450,
        "valor_mercadoria": 228371,
        "cidade_origem": "Manaus, AM", "cidade_destino": "Santa Bárbara D'Oeste, SP",
        "esperado": {
            "frete_base": 36337.80, "gris": 342.56, "ad_valorem": 799.30,
            "taxa_fluvial": 274.05, "frete_sem_imposto": 37753.70, "pis_cofins": 1132.61,
            "icms": 5148.23, "frete_final": 44034.55,
        },
    },
    {
        "nome": "FTL Manaus/AM->São Lourenço/MG (linha 101)",
        "tipo": "lotacao",
        "peso": 8096, "m3": 0, "distancia_km": 3700,
        "valor_mercadoria": 228371,
        "cidade_origem": "Manaus, AM", "cidade_destino": "São Lourenço, MG",
        "esperado": {
            "frete_base": 39264.61, "gris": 342.56, "ad_valorem": 799.30,
            "taxa_fluvial": 274.05, "frete_sem_imposto": 40680.51, "pis_cofins": 1220.42,
            "icms": 5547.34, "frete_final": 47448.27,
        },
    },
    {
        "nome": "FTL Manaus/AM->Horizonte/CE (linha 102)",
        "tipo": "lotacao",
        "peso": 8096, "m3": 0, "distancia_km": 3100,
        "valor_mercadoria": 228371,
        "cidade_origem": "Manaus, AM", "cidade_destino": "Horizonte, CE",
        "esperado": {
            "frete_base": 27664.81, "gris": 342.56, "ad_valorem": 799.30,
            "taxa_fluvial": 274.05, "frete_sem_imposto": 29080.71, "pis_cofins": 872.42,
            "icms": 3965.55, "frete_final": 33918.68,
        },
    },
    {
        "nome": "FTL Cajamar/SP->Belém/PA (linha 117)",
        "tipo": "lotacao",
        "peso": 2200, "m3": 0, "distancia_km": 2900,
        "valor_mercadoria": 115000,
        "cidade_origem": "Cajamar, SP", "cidade_destino": "Belém, PA",
        "esperado": {
            "frete_base": 21489.48, "gris": 230.0, "ad_valorem": 460.0,
            "taxa_fluvial": 0.0, "frete_sem_imposto": 22179.48, "pis_cofins": 665.38,
            "icms": 1669.42, "frete_final": 24514.28,
        },
    },
]


def _rodar_caso(caso: dict, transporte: str, categoria: str, sla: str) -> dict:
    paletes = _palete_sintetico(caso["m3"])
    if caso["tipo"] == "fracionado":
        veiculo = fs.escolher_veiculo(caso["peso"], paletes, fs.parametros.buscar_transporte(transporte)).veiculo.nome
        resultado = fs.calcular_orcamento_fracionado(
            peso=caso["peso"], paletes=paletes, distancia=caso["distancia_km"],
            valor_mercadoria=caso["valor_mercadoria"], categoria=categoria, transporte=transporte,
            sla=sla, veiculo=veiculo,
            cidade_origem=caso["cidade_origem"], cidade_destino=caso["cidade_destino"],
        )
    else:
        resultado = fs.calcular_orcamento(
            peso=caso["peso"], paletes=paletes, distancia=caso["distancia_km"],
            valor_mercadoria=caso["valor_mercadoria"], categoria=categoria, transporte=transporte,
            sla=sla, cidade_origem=caso["cidade_origem"], cidade_destino=caso["cidade_destino"],
        )
    ci = resultado["calculos_intermediarios"]
    # Pedágio desconsiderado do comparativo a pedido do usuário: sem praça
    # cadastrada pra essas rotas, o sistema sempre aplica o fallback de 4%
    # (PEDAGIO_PCT_FALLBACK, ver _pedagio_aplicado) -- um conceito sem
    # equivalente direto na planilha (que usa uma taxa fluvial separada só
    # pra destino AM). Subtrai o valor de pedágio efetivamente somado nos
    # totais, sem mudar nenhuma regra de cálculo em frete_service.py.
    pedagio = ci["pedagio"]
    return {
        "frete_base": ci["frete_base"],
        "gris": next((t["valor_aplicado"] for t in ci["taxas_adicionais"] if t["nome"] == "GRIS"), 0.0),
        "ad_valorem": next((t["valor_aplicado"] for t in ci["taxas_adicionais"] if t["nome"] == "Ad Valorem"), 0.0),
        "frete_sem_imposto": ci["total_custo_operacao"] + ci["total_impostos_taxas"] - pedagio,
        "pis_cofins": ci["valor_pis_cofins"],
        "icms": ci["valor_icms"],
        "frete_final": resultado["resultado"]["frete_total"] - pedagio,
    }


def _diff_pct(esperado: float, obtido: float) -> float:
    if esperado == 0:
        return 0.0 if obtido == 0 else 100.0
    return abs(obtido - esperado) / abs(esperado) * 100


def main():
    filtro_tipo = sys.argv[1] if len(sys.argv) > 1 else None
    casos = [c for c in CASOS if filtro_tipo is None or c["tipo"] == filtro_tipo]
    if filtro_tipo and not casos:
        print(f"Nenhum caso com tipo={filtro_tipo!r}. Tipos disponíveis: {sorted({c['tipo'] for c in CASOS})}")
        return

    fs.carregar_parametros()
    transporte, categoria, sla = _parametros_neutros()
    print(f"Transporte neutro: {transporte!r} | Categoria neutra: {categoria!r} | SLA neutro: {sla!r}\n")

    # taxa_fluvial fora da comparação a pedido do usuário: o pedágio
    # fallback (PEDAGIO_PCT_FALLBACK) ocupa esse mesmo "slot" no resultado
    # do sistema mas é um conceito diferente da taxa fluvial de 1% da
    # planilha -- comparar os dois junto só gera ruído sem relação real.
    campos = ["frete_base", "gris", "ad_valorem", "frete_sem_imposto", "pis_cofins", "icms", "frete_final"]
    divergencias_por_campo = {c: 0 for c in campos}
    casos_ok = 0
    casos_erro = 0

    for caso in casos:
        print("=" * 100)
        print(caso["nome"], f"[{caso['tipo']}]")
        try:
            obtido = _rodar_caso(caso, transporte, categoria, sla)
        except (fs.FreteInputError, fs.FreteConfigError) as e:
            casos_erro += 1
            print(f"  ERRO ao calcular: {e}")
            continue

        esperado = caso["esperado"]
        print(f"  {'campo':<20}{'planilha':>15}{'sistema':>15}{'dif. abs':>15}{'dif. %':>10}")
        bateu_tudo = True
        for campo in campos:
            e = esperado[campo]
            o = obtido[campo]
            dif = o - e
            pct = _diff_pct(e, o)
            marca = "" if pct <= TOLERANCIA_PCT else "  <-- diverge"
            if pct > TOLERANCIA_PCT:
                divergencias_por_campo[campo] += 1
                bateu_tudo = False
            print(f"  {campo:<20}{e:>15.2f}{o:>15.2f}{dif:>15.2f}{pct:>9.1f}%{marca}")
        casos_ok += 1 if bateu_tudo else 0

    total_rodados = len(casos) - casos_erro
    print("\n" + "=" * 100)
    print("RESUMO")
    print(f"  Casos com erro (não calculou): {casos_erro}/{len(casos)}")
    print(f"  Casos que bateram em todos os campos (tolerância {TOLERANCIA_PCT}%): {casos_ok}/{total_rodados}")
    print("  Divergências por campo (quantos casos, de olhando só os que rodaram, divergiram nesse campo):")
    for campo, n in divergencias_por_campo.items():
        if total_rodados:
            print(f"    {campo:<20}{n}/{total_rodados}")


if __name__ == "__main__":
    main()
