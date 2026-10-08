# Desenvolvedor Chefe: RenanFolha

"""
Lógica de cálculo de frete. Os parâmetros (veículos, taxas adicionais,
coleta por cidade, categorias, transportes, SLAs, filiais) são lidos do
banco SQLite (frete.db) a cada recarga — edite pela tela "Tabela de
Preços" ou direto no banco com o DB Browser for SQLite, e chame POST
/admin/reload para aplicar (a tela já faz isso sozinha a cada edição).

Fórmula do frete principal (por veículo):
    custo_km = veiculo.tarifa_km * distancia
    peso_excedente_kg = max(peso_considerado - veiculo.ate, 0)
    custo_peso_excedente = (peso_excedente_kg / 1000) * veiculo.valor_tonelada_excedente
    frete_base = custo_km + custo_peso_excedente
    frete_ajustado = frete_base * categoria.multiplicador * transporte.multiplicador * sla.multiplicador

peso_excedente_kg normalmente é zero — o veículo já é escolhido pra
cobrir o peso considerado (buscar_veiculo_por_peso). Só fica positivo
quando a carga ultrapassa até o maior veículo cadastrado: nesse caso o
sistema usa esse veículo mesmo assim (fallback) e
valor_tonelada_excedente vira uma sobretaxa pelas toneladas que
passaram do limite máximo disponível.

Em cima disso somam-se: taxas adicionais (fixas em R$ ou % do valor da
mercadoria) e a taxa de coleta (quando há retirada no cliente — usa
preço fixo se a rota cidade do cliente -> filial + veículo estiver
cadastrada, senão cai na faixa por km).

As tabelas antigas de "tipo de frete" (faixas_peso/faixas_distancia)
continuam existindo no banco por compatibilidade, mas não são mais
usadas no cálculo — o veículo assumiu esse papel.
"""

import datetime
import re
import threading
from dataclasses import dataclass

import frete_db as db

_lock = threading.Lock()

_UFS_BR = {
    "acre", "alagoas", "amapá", "amazonas", "bahia", "ceará", "distrito federal",
    "espírito santo", "goiás", "maranhão", "mato grosso", "mato grosso do sul",
    "minas gerais", "pará", "paraíba", "paraná", "pernambuco", "piauí",
    "rio de janeiro", "rio grande do norte", "rio grande do sul", "rondônia",
    "roraima", "santa catarina", "são paulo", "sergipe", "tocantins",
}
_UFS_BR_SIGLAS = {
    "ac", "al", "ap", "am", "ba", "ce", "df", "es", "go", "ma", "mt", "ms",
    "mg", "pa", "pb", "pr", "pe", "pi", "rj", "rn", "rs", "ro", "rr", "sc",
    "sp", "se", "to",
}
# Cidades (normalizadas, ver db.normalizar_texto) classificadas como
# "CAPITAL" por UF pra fins de custo do Fracionado (ver
# _classificar_capital_interior/_custo_fracionado_destino_aplicavel) --
# inclui a região metropolitana quando a planilha legada (aba "Capitais")
# trata ela como capital pra efeito de tarifa (ex: Guarulhos/Barueri/Osasco
# em SP, Ananindeua em PA), não só o município-sede. Qualquer cidade fora
# dessa lista cai em "INTERIOR". Referência nacional estável -- não
# cadastrada em tela, ao contrário dos dados de preço.
CAPITAIS_BR: dict[str, set[str]] = {
    "AC": {"rio branco"},
    "AL": {"maceio"},
    "AM": {"manaus"},
    "AP": {"macapa"},
    "BA": {"salvador"},
    "CE": {"fortaleza"},
    "DF": {"brasilia"},
    "ES": {"vitoria"},
    "GO": {"goiania"},
    "MA": {"sao luis"},
    "MG": {"belo horizonte"},
    "MS": {"campo grande"},
    "MT": {"cuiaba"},
    "PA": {"ananindeua", "belem"},
    "PB": {"joao pessoa"},
    "PE": {"recife"},
    "PI": {"teresina"},
    "PR": {"curitiba"},
    "RJ": {"rio de janeiro"},
    "RN": {"natal"},
    "RO": {"porto velho"},
    "RR": {"boa vista"},
    "RS": {"porto alegre"},
    "SC": {"florianopolis"},
    "SE": {"aracaju"},
    "SP": {"barueri", "guarulhos", "osasco", "sao bernardo dos campos", "sao paulo"},
    "TO": {"palmas"},
}

_CEP_SOLTO_REGEX = re.compile(r"^\d{5}-?\d{3}$")
# O Nominatim separa a UF em segmento próprio ("..., São Paulo, SP, Brasil"),
# mas o formatted_address do Google Maps cola a sigla no mesmo segmento da
# cidade ("..., Manaus - AM, ..."). Sem remover esse sufixo, a cidade
# extraída ficaria "Manaus - AM" em vez de "Manaus", e o casamento de
# taxa regional (comparação exata, ver _taxas_regionais_aplicaveis) falharia
# silenciosamente pra quem usa GOOGLE_MAPS_API_KEY.
_SUFIXO_UF_REGEX = re.compile(
    r"\s*-\s*(?:" + "|".join(_UFS_BR_SIGLAS) + r")\s*$", re.IGNORECASE
)


def _sem_sufixo_uf(cidade: str) -> str:
    return _SUFIXO_UF_REGEX.sub("", cidade).strip()


def _valor_taxa(tipo: str, valor: float, valor_mercadoria: float) -> float:
    """Aplica uma taxa (adicional, regional ou de balsa) conforme seu tipo
    cadastrado: 'percentual' incide sobre o valor da mercadoria, 'fixo' é o
    próprio valor cadastrado em R$."""
    return valor_mercadoria * (valor / 100) if tipo == "percentual" else valor


# Custo extra: categorias fixas escolhidas por orçamento (não é um
# catálogo cadastrável como as taxas adicionais) — a pessoa que cota
# marca quais categorias se aplicam e digita o valor (R$) de cada uma na
# hora, ver calcular_orcamento.
CATEGORIAS_CUSTO_EXTRA = ["Paletização", "Carga", "Descarga", "Entrega Adicional", "Diversos"]

# Margem de lucro: fixa, não é mais digitável por quem cota (markup
# simples sobre o frete_total, ver calcular_orcamento).
MARGEM_LUCRO_PADRAO = 40

# Markup mínimo garantido sobre custo da operação + impostos/taxas (antes
# de PIS/COFINS, ICMS e da margem de lucro): se depois de aplicar tudo o
# frete_total ficar abaixo de MARKUP_MINIMO vezes essa base, a diferença é
# somada na linha de impostos/taxas pra fechar exatamente nesse piso (ver
# calcular_orcamento/calcular_orcamento_fracionado) -- a margem de lucro em
# si continua fixa em MARGEM_LUCRO_PADRAO% só do custo da operação; esse
# ajuste existe pra garantir o markup final mesmo quando impostos/taxas são
# grandes o bastante (ex: GRIS/Ad Valorem altos) pra a margem fixa sozinha
# não bastar.
MARKUP_MINIMO = 1.4

# Pedágio: quando não há praça cadastrada pro corredor da rota + eixos do
# veículo (ver pedagio_rota_aplicavel), aplica esse % sobre frete + custos
# operacionais + taxas + PIS/COFINS + ICMS previstos (sem margem, ver
# _pedagio_aplicado) como estimativa padrão em vez de confiar só na
# estimativa genérica do Google Maps ou deixar em R$ 0.
PEDAGIO_PCT_FALLBACK = 4.0

# Acréscimo fixo (R$) somado ao custo tabelado de lotação por destino
# antes da margem de lucro, quando a rota está cadastrada em
# custos_lotacao_destino (ver _custo_lotacao_destino_aplicavel) --
# replicado da fórmula da planilha legada (COTAÇÃO SSONIC 2026, aba
# Base Geral, coluna FRETE), onde esse valor aparece fixo em toda linha
# de lotação/fracionado independente de peso ou rota; a origem exata
# desse valor (taxa de documentação? seguro mínimo?) não está
# documentada na planilha, mas é necessário pra bater o frete_base
# exatamente com os dados históricos.
TAXA_FIXA_LOTACAO_TABELA = 33.1

# Prazo estimado (dias úteis) por rota: 1 dia base + 1 dia adicional a
# cada PRAZO_KM_POR_DIA_ADICIONAL km rodados (achado #7 do relatório
# Teste_Completo_FTL_2026_Sistema_vs_Planilha.xlsx -- o sistema devolvia
# sempre "5 dias úteis" fixo, independente da distância real da rota, ver
# _prazo_estimado_dias_uteis). Rotas com travessia de balsa somam mais
# PRAZO_DIAS_EXTRA_BALSA dias (PRAZO_DIAS_EXTRA_BALSA_SECA de outubro a
# dezembro, quando o nível do rio baixa e a travessia demora mais).
PRAZO_KM_POR_DIA_ADICIONAL = 500
PRAZO_DIAS_EXTRA_BALSA = 5
PRAZO_DIAS_EXTRA_BALSA_SECA = 7
_MESES_SECA_BALSA = {10, 11, 12}

# Nomes de taxas adicionais que podem ser digitadas por orçamento (ver
# gris_pct/ad_valorem_pct em calcular_orcamento/calcular_orcamento_fracionado
# e _taxas_adicionais_aplicadas) -- o % digitado substitui o % cadastrado em
# Tabela de Preços pra essa taxa, nunca abaixo dele (o cadastrado é o piso).
_NOME_TAXA_GRIS = "GRIS"
_NOME_TAXA_AD_VALOREM = "Ad Valorem"


class FreteConfigError(Exception):
    """Erro ao ler/validar os parâmetros do banco."""


class FreteInputError(Exception):
    """Erro de validação dos dados de entrada do orçamento."""


@dataclass
class FaixaDistancia:
    de: float
    ate: float
    taxa_fixa: float
    tarifa_km: float


@dataclass
class FaixaPeso:
    de: float
    ate: float
    tarifa_base: float
    custo_kg_adicional: float


@dataclass
class FaixaCustoFracionado:
    """Custo (R$) de um componente (coleta/embarque/entrega) do Fracionado
    por faixa de peso fixa (10/20/30/50/70/100/150/200kg) + R$/kg acima de
    200kg (excedente_kg) -- replica a estrutura das abas "TB FRACIONADO -
    CUSTO (SP/AM)" da planilha legada (ver custos_fracionado_destino e
    _custo_fracionado_destino_aplicavel)."""
    v10: float
    v20: float
    v30: float
    v50: float
    v70: float
    v100: float
    v150: float
    v200: float
    excedente_kg: float

    def calcular(self, peso: float) -> float:
        for limite, valor in (
            (10, self.v10), (20, self.v20), (30, self.v30), (50, self.v50),
            (70, self.v70), (100, self.v100), (150, self.v150), (200, self.v200),
        ):
            if peso <= limite:
                return valor
        return self.v200 + self.excedente_kg * (peso - 200)


@dataclass
class Categoria:
    nome: str
    multiplicador: float


@dataclass
class Transporte:
    nome: str
    multiplicador: float
    fator_cubagem: float


@dataclass
class SLA:
    nome: str
    multiplicador: float
    prazo_dias: int


@dataclass
class Filial:
    nome: str
    endereco: str
    latitude: float | None
    longitude: float | None
    uf: str = ""  # UF onde a filial fica (ver comentário na tabela filiais) -- usado pelo cálculo de ICMS


@dataclass
class Veiculo:
    nome: str
    de: float
    ate: float
    tarifa_km: float
    valor_tonelada_excedente: float
    tarifa_km_retorno: float = 0
    tarifa_km_manutencao: float = 0
    capacidade_m3: float = 0
    # % da capacidade_m3 que pode realmente ser ocupada (o resto fica de
    # margem — carga não empilha 100% perfeita, precisa espaço pra
    # amarração etc.). Editável por veículo porque cada um tem uma
    # realidade de carregamento diferente (ex: Carreta aproveita mais %
    # que uma Van). Antes era um valor fixo de 80% pra todos.
    percentual_capacidade_util: float = 80
    # Usado só pra achar o preço certo nas praças de pedágio cadastradas
    # (ver pedagio_rota_aplicavel) -- 0 = não cadastrado, o veículo fica
    # de fora do cálculo automático de pedágio até ser preenchido.
    numero_eixos: int = 0


@dataclass
class FaixaKmVeiculo:
    veiculo: str
    de: float
    ate: float
    tarifa_km: float


@dataclass
class TaxaAdicional:
    nome: str
    tipo: str  # 'fixo' ou 'percentual'
    valor: float


@dataclass
class TaxaRegional:
    cidade: str
    nome: str
    tipo: str  # 'fixo' ou 'percentual'
    valor: float


@dataclass
class TaxaBalsa:
    cidade_origem: str
    cidade_destino: str
    veiculo: str
    tipo: str  # 'fixo' ou 'percentual'
    valor: float


@dataclass
class ColetaCidadeFixa:
    filial_origem: str
    cidade_destino: str  # uma ou mais cidades separadas por vírgula
    veiculo: str
    valor_fixo: float


@dataclass
class PrioridadeRota:
    estado_origem: str  # UF (sigla), ou "*"
    cidade_destino: str
    filial_escala: str


@dataclass
class PracaPedagio:
    id: int
    nome: str
    rodovia: str
    concessionaria: str
    valores_por_eixo: dict[int, float]  # {2: 12.4, 3: 18.6, ...}


@dataclass
class PedagioRota:
    cidade_origem: str  # ou "*"
    cidade_destino: str
    praca_id: int


@dataclass
class DistanciaFixa:
    cidade_origem: str  # ou "*"
    cidade_destino: str
    distancia_km: float


@dataclass
class AliquotaIcms:
    estado_origem: str  # UF (sigla), ou "*"
    estado_destino: str  # UF (sigla), ou "*"
    aliquota: float  # % aplicada "por dentro" (gross-up) sobre o frete_total


@dataclass
class TaxaDiariaVeiculo:
    uf: str  # sigla da UF, sem curinga "*" (ver _diaria_veiculo_aplicada)
    valor_carreta: float
    valor_cavalo: float


class ParametrosFrete:
    """Mantém em memória os parâmetros lidos do banco."""

    def __init__(self):
        self.veiculos: dict[str, Veiculo] = {}
        self.veiculos_por_peso: list[Veiculo] = []
        self.faixas_km_veiculo: dict[str, list[FaixaKmVeiculo]] = {}
        self.taxas_adicionais: list[TaxaAdicional] = []
        self.taxas_regionais: list[TaxaRegional] = []
        self.taxas_balsa: list[TaxaBalsa] = []
        self.prioridades_rota: list[PrioridadeRota] = []
        self.pracas_pedagio: dict[int, PracaPedagio] = {}
        self.pedagios_rota: list[PedagioRota] = []
        self.distancias_fixas: list[DistanciaFixa] = []
        self.aliquotas_icms: list[AliquotaIcms] = []
        self.aliquota_pis_cofins: float = 0.0
        self.custos_lotacao_destino: dict[tuple[str, str, str], float] = {}
        self.custos_fracionado_destino: dict[tuple[str, str, str, str], "FaixaCustoFracionado"] = {}
        self.prazo_fracionado_destino: dict[tuple[str, str, str], int] = {}
        self.taxas_diaria_veiculo: list[TaxaDiariaVeiculo] = []
        self.coleta_cidades_fixas: list[ColetaCidadeFixa] = []
        self.faixas_coleta: list[FaixaDistancia] = []
        # Frete Fracionado (ver calcular_orcamento_fracionado): faixas por
        # peso e por distância cadastradas com tipo_frete='Fracionado' nas
        # mesmas tabelas faixas_peso/faixas_distancia que já existiam no
        # banco (linhas de tipo_frete='Carreta Fechada' continuam existindo
        # mas não são lidas aqui -- ver nota no topo do arquivo).
        self.faixas_peso_fracionado: list[FaixaPeso] = []
        self.faixas_distancia_fracionado: list[FaixaDistancia] = []
        self.categorias: dict[str, Categoria] = {}
        self.transportes: dict[str, Transporte] = {}
        self.slas: dict[str, SLA] = {}
        self.filiais: dict[str, Filial] = {}

    def load(self):
        # Não chama db.init_db() aqui: essa função reexecuta o schema
        # inteiro (CREATE TABLE, migrações, seed) e é chamada depois de
        # toda escrita admin (ver main.py) — rodar tudo isso a cada save
        # de uma linha só seria desperdício. db.init_db() já roda uma vez
        # no startup da API (main.py lifespan), antes de qualquer load().
        with db.get_connection() as conn:
            self.veiculos = {
                r["nome"].strip().lower(): Veiculo(
                    r["nome"], r["de"], r["ate"], r["tarifa_km"], r["valor_tonelada_excedente"],
                    r["tarifa_km_retorno"], r["tarifa_km_manutencao"], r["capacidade_m3"],
                    r["percentual_capacidade_util"], r["numero_eixos"],
                )
                for r in conn.execute("SELECT * FROM veiculos")
            }
            self.veiculos_por_peso = sorted(self.veiculos.values(), key=lambda v: v.de)
            self.faixas_km_veiculo = {}
            for r in conn.execute("SELECT * FROM faixas_km_veiculo ORDER BY de"):
                chave = r["veiculo"].strip().lower()
                self.faixas_km_veiculo.setdefault(chave, []).append(
                    FaixaKmVeiculo(r["veiculo"], r["de"], r["ate"], r["tarifa_km"])
                )
            self.taxas_adicionais = [
                TaxaAdicional(r["nome"], r["tipo"], r["valor"])
                for r in conn.execute("SELECT * FROM taxas_adicionais")
            ]
            self.taxas_regionais = [
                TaxaRegional(r["cidade"], r["nome"], r["tipo"], r["valor"])
                for r in conn.execute("SELECT * FROM taxas_regionais")
            ]
            self.taxas_balsa = [
                TaxaBalsa(r["cidade_origem"], r["cidade_destino"], r["veiculo"], r["tipo"], r["valor"])
                for r in conn.execute("SELECT * FROM taxas_balsa")
            ]
            self.prioridades_rota = [
                PrioridadeRota(r["estado_origem"], r["cidade_destino"], r["filial_escala"])
                for r in conn.execute("SELECT * FROM prioridades_rota")
            ]
            self.pracas_pedagio = {
                r["id"]: PracaPedagio(
                    r["id"], r["nome"], r["rodovia"], r["concessionaria"],
                    {n: r[f"valor_eixo_{n}"] for n in db.EIXOS_PEDAGIO},
                )
                for r in conn.execute("SELECT * FROM pracas_pedagio")
            }
            self.pedagios_rota = [
                PedagioRota(r["cidade_origem"], r["cidade_destino"], r["praca_id"])
                for r in conn.execute("SELECT * FROM pedagios_rota")
            ]
            self.distancias_fixas = [
                DistanciaFixa(r["cidade_origem"], r["cidade_destino"], r["distancia_km"])
                for r in conn.execute("SELECT * FROM distancias_fixas")
            ]
            self.aliquotas_icms = [
                AliquotaIcms(r["estado_origem"], r["estado_destino"], r["aliquota"])
                for r in conn.execute("SELECT * FROM aliquotas_icms")
            ]
            linha_pis_cofins = conn.execute(
                "SELECT aliquota FROM aliquota_pis_cofins WHERE id = 1"
            ).fetchone()
            self.aliquota_pis_cofins = linha_pis_cofins["aliquota"] if linha_pis_cofins else 0.0
            self.custos_lotacao_destino = {
                (r["origem_tabela"], r["uf_destino"], r["cidade_destino_norm"]): r["custo_total"]
                for r in conn.execute("SELECT * FROM custos_lotacao_destino")
            }
            self.custos_fracionado_destino = {
                (r["origem_tabela"], r["uf_destino"], r["capital_interior"], r["componente"]): FaixaCustoFracionado(
                    r["v10"], r["v20"], r["v30"], r["v50"], r["v70"], r["v100"], r["v150"], r["v200"],
                    r["excedente_kg"],
                )
                for r in conn.execute("SELECT * FROM custos_fracionado_destino")
            }
            self.prazo_fracionado_destino = {
                (r["origem_tabela"], r["uf_destino"], r["capital_interior"]): r["dias_uteis"]
                for r in conn.execute("SELECT * FROM prazo_fracionado_destino")
            }
            self.taxas_diaria_veiculo = [
                TaxaDiariaVeiculo(r["uf"], r["valor_carreta"], r["valor_cavalo"])
                for r in conn.execute("SELECT * FROM taxas_diaria_veiculo")
            ]
            self.coleta_cidades_fixas = [
                ColetaCidadeFixa(r["filial_origem"], r["cidade_destino"], r["veiculo"], r["valor_fixo"])
                for r in conn.execute("SELECT * FROM coleta_cidades_fixas ORDER BY id")
            ]
            self.faixas_coleta = sorted(
                (FaixaDistancia(r["de"], r["ate"], r["taxa_fixa"], r["tarifa_km"])
                 for r in conn.execute("SELECT * FROM faixas_coleta")),
                key=lambda f: f.de,
            )
            self.faixas_peso_fracionado = sorted(
                (FaixaPeso(r["de"], r["ate"], r["tarifa_base"], r["custo_kg_adicional"])
                 for r in conn.execute("SELECT * FROM faixas_peso WHERE tipo_frete = 'Fracionado'")),
                key=lambda f: f.de,
            )
            self.faixas_distancia_fracionado = sorted(
                (FaixaDistancia(r["de"], r["ate"], r["taxa_fixa"], r["tarifa_km"])
                 for r in conn.execute("SELECT * FROM faixas_distancia WHERE tipo_frete = 'Fracionado'")),
                key=lambda f: f.de,
            )
            self.categorias = {
                r["nome"].strip().lower(): Categoria(r["nome"], r["multiplicador"])
                for r in conn.execute("SELECT * FROM categorias")
            }
            self.transportes = {
                r["nome"].strip().lower(): Transporte(r["nome"], r["multiplicador"], r["fator_cubagem"])
                for r in conn.execute("SELECT * FROM transportes")
            }
            self.slas = {
                r["nome"].strip().lower(): SLA(r["nome"], r["multiplicador"], r["prazo_dias"])
                for r in conn.execute("SELECT * FROM slas")
            }
            self.filiais = {
                r["nome"].strip().lower(): Filial(r["nome"], r["endereco"], r["latitude"], r["longitude"], r["uf"])
                for r in conn.execute("SELECT * FROM filiais")
            }

        if not self.veiculos:
            raise FreteConfigError("Nenhum veículo cadastrado (tabela veiculos).")
        if not self.faixas_coleta:
            raise FreteConfigError("Nenhuma faixa de coleta cadastrada (tabela faixas_coleta).")
        # Faixas de peso/distância do Fracionado NÃO são exigidas aqui
        # (ao contrário das outras tabelas acima) -- um banco existente
        # pode não ter nenhuma linha ainda (o recurso é novo). Falta de
        # faixa só quebra quem realmente tentar cotar um Fracionado (ver
        # buscar_faixa_peso_fracionado/buscar_faixa_distancia_fracionado),
        # não o carregamento dos parâmetros pra todo o resto do sistema.
        if not self.categorias:
            raise FreteConfigError("Nenhuma categoria cadastrada (tabela categorias).")
        if not self.transportes:
            raise FreteConfigError("Nenhum transporte cadastrado (tabela transportes).")
        if not self.slas:
            raise FreteConfigError("Nenhum SLA cadastrado (tabela slas).")
        if not self.filiais:
            raise FreteConfigError("Nenhuma filial cadastrada (tabela filiais).")

    # ---- lookups ----

    def buscar_veiculo(self, nome: str) -> Veiculo:
        v = self.veiculos.get(nome.strip().lower())
        if not v:
            opcoes = ", ".join(x.nome for x in self.veiculos.values())
            raise FreteInputError(f"Veículo '{nome}' inválido. Opções: {opcoes}")
        return v

    def buscar_veiculo_por_peso(self, peso_considerado: float) -> Veiculo:
        """Escolhe automaticamente o veículo cuja faixa (de/até, em kg)
        cobre o peso considerado — igual funcionava com as antigas
        faixas de peso, só que agora cada faixa já vem com o preço/km
        do veículo correspondente."""
        candidatos = [v for v in self.veiculos_por_peso if v.de <= peso_considerado]
        if not candidatos:
            raise FreteInputError(
                f"Peso {peso_considerado}kg abaixo da menor faixa de veículo configurada."
            )
        # entre os candidatos cuja faixa começa <= peso, pega o de faixa
        # mais alta que ainda cobre o peso (ate > peso), senão o maior de todos
        dentro_da_faixa = [v for v in candidatos if peso_considerado < v.ate]
        if dentro_da_faixa:
            return max(dentro_da_faixa, key=lambda v: v.de)
        return max(candidatos, key=lambda v: v.de)

    def buscar_veiculo_por_peso_e_volume(self, peso_considerado: float, volume_total_m3: float) -> Veiculo:
        """Primeiro escolhe o veículo pela faixa de peso (como sempre foi).
        Se a carga não couber na capacidade útil (m³) desse veículo —
        capacidade_m3 × percentual_capacidade_util, esse último editável
        por veículo na Tabela de Preços (era fixo em 80% antes) — sobe
        para o próximo veículo maior (por peso) que tenha espaço. Um
        veículo sem capacidade_m3 cadastrada (0) é tratado como sem
        limite de volume, pra não quebrar quem ainda não configurou isso."""
        escolhido = self.buscar_veiculo_por_peso(peso_considerado)
        if volume_total_m3 <= 0:
            return escolhido

        def capacidade_disponivel(v: Veiculo) -> float:
            return v.capacidade_m3 * (v.percentual_capacidade_util / 100)

        def cabe(v: Veiculo) -> bool:
            return v.capacidade_m3 <= 0 or volume_total_m3 <= capacidade_disponivel(v)

        if cabe(escolhido):
            return escolhido

        maiores = sorted(
            (v for v in self.veiculos_por_peso if v.de >= escolhido.de),
            key=lambda v: v.de,
        )
        for v in maiores:
            if cabe(v):
                return v

        raise FreteInputError(
            f"Volume da carga ({volume_total_m3:.3f} m³) ultrapassa a capacidade útil configurada de todos os "
            f"veículos disponíveis a partir de '{escolhido.nome}'. Cadastre um veículo maior na Tabela de "
            f"Preços ou revise as dimensões dos paletes informados."
        )

    def buscar_faixa_coleta(self, distancia: float) -> FaixaDistancia:
        candidatas = [f for f in self.faixas_coleta if f.de <= distancia]
        if not candidatas:
            raise FreteInputError(f"Distância de coleta {distancia}km abaixo da menor faixa configurada.")
        return candidatas[-1]

    def buscar_faixa_peso_fracionado(self, peso_considerado: float) -> FaixaPeso:
        """Faixa de peso do Fracionado que cobre peso_considerado — mesma
        regra de tarifa_km_efetiva: pega a faixa de maior 'de' que ainda
        seja <= o peso (não soma progressivamente pelas faixas menores,
        só a que o peso total cai é que vale)."""
        if not self.faixas_peso_fracionado:
            raise FreteConfigError(
                "Nenhuma faixa de peso do Fracionado cadastrada — cadastre em Tabela de Preços → Fracionado."
            )
        candidatas = [f for f in self.faixas_peso_fracionado if f.de <= peso_considerado]
        if not candidatas:
            raise FreteInputError(f"Peso {peso_considerado}kg abaixo da menor faixa de peso do Fracionado configurada.")
        return candidatas[-1]

    def buscar_faixa_distancia_fracionado(self, distancia: float) -> FaixaDistancia:
        """Faixa de distância do Fracionado que cobre a distância faturável
        — mesma regra de buscar_faixa_peso_fracionado (uma faixa só, não
        progressiva)."""
        if not self.faixas_distancia_fracionado:
            raise FreteConfigError(
                "Nenhuma faixa de distância do Fracionado cadastrada — cadastre em Tabela de Preços → Fracionado."
            )
        candidatas = [f for f in self.faixas_distancia_fracionado if f.de <= distancia]
        if not candidatas:
            raise FreteInputError(f"Distância {distancia}km abaixo da menor faixa de distância do Fracionado configurada.")
        return candidatas[-1]

    def buscar_coleta_cidade_fixa(
        self, filial_origem: str, cidade_destino: str, veiculo: str
    ) -> ColetaCidadeFixa | None:
        """Preço fixo de coleta pra rota filial_origem -> cidade_destino +
        veículo, se cadastrado — mesma semântica de
        frete_db.buscar_coleta_cidade_fixa, mas em memória (já carregado em
        self.coleta_cidades_fixas, em vez de reabrir o banco a cada
        orçamento). A cidade pode estar em qualquer posição da lista
        guardada na linha."""
        filial_alvo = db.normalizar_texto(filial_origem)
        veic_alvo = db.normalizar_texto(veiculo)
        alvo = db.normalizar_texto(cidade_destino)
        for c in self.coleta_cidades_fixas:
            if db.normalizar_texto(c.filial_origem) != filial_alvo or db.normalizar_texto(c.veiculo) != veic_alvo:
                continue
            if alvo in {db.normalizar_texto(x) for x in db._dividir_cidades(c.cidade_destino)}:
                return c
        return None

    def buscar_coleta_cidade_fixa_outros_veiculos(
        self, filial_origem: str, cidade_destino: str, veiculo_atual: str
    ) -> list[str]:
        """Veículos (diferentes do informado) que têm preço fixo de coleta
        cadastrado pra essa mesma filial+cidade — mesma semântica de
        frete_db.buscar_coleta_cidade_fixa_outros_veiculos, em memória."""
        filial_alvo = db.normalizar_texto(filial_origem)
        alvo = db.normalizar_texto(cidade_destino)
        veic_atual = db.normalizar_texto(veiculo_atual)
        encontrados = set()
        for c in self.coleta_cidades_fixas:
            if db.normalizar_texto(c.filial_origem) != filial_alvo:
                continue
            if db.normalizar_texto(c.veiculo) == veic_atual:
                continue
            if alvo in {db.normalizar_texto(x) for x in db._dividir_cidades(c.cidade_destino)}:
                encontrados.add(c.veiculo)
        return sorted(encontrados)

    def tarifa_km_efetiva(self, veiculo: Veiculo, distancia: float) -> tuple[float, bool]:
        """R$/km a usar no frete principal: se o veículo tiver faixas de km
        cadastradas (Tabela de Preços → "Faixas de KM por Veículo"), usa a
        tarifa escalonada pela distância em vez do tarifa_km fixo do
        veículo. Devolve (tarifa, veio_de_faixa) — o segundo valor é só
        pra deixar isso visível na memória de cálculo do orçamento.
        Veículo sem nenhuma faixa cadastrada continua com o tarifa_km fixo
        de sempre."""
        faixas = self.faixas_km_veiculo.get(veiculo.nome.strip().lower())
        if not faixas:
            return veiculo.tarifa_km, False
        candidatas = [f for f in faixas if f.de <= distancia]
        if not candidatas:
            # distância abaixo da menor faixa cadastrada -- cai pro
            # tarifa_km fixo em vez de travar o orçamento com erro
            return veiculo.tarifa_km, False
        return candidatas[-1].tarifa_km, True

    def buscar_categoria(self, nome: str) -> Categoria:
        cat = self.categorias.get(nome.strip().lower())
        if not cat:
            opcoes = ", ".join(c.nome for c in self.categorias.values())
            raise FreteInputError(f"Categoria '{nome}' inválida. Opções: {opcoes}")
        return cat

    def buscar_transporte(self, nome: str) -> Transporte:
        t = self.transportes.get(nome.strip().lower())
        if not t:
            opcoes = ", ".join(x.nome for x in self.transportes.values())
            raise FreteInputError(f"Método de transporte '{nome}' inválido. Opções: {opcoes}")
        return t

    def buscar_sla(self, nome: str) -> SLA:
        s = self.slas.get(nome.strip().lower())
        if not s:
            opcoes = ", ".join(x.nome for x in self.slas.values())
            raise FreteInputError(f"SLA '{nome}' inválido. Opções: {opcoes}")
        return s

    def buscar_filial(self, nome: str) -> Filial:
        f = self.filiais.get(nome.strip().lower())
        if not f:
            opcoes = ", ".join(x.nome for x in self.filiais.values())
            raise FreteInputError(f"Filial '{nome}' inválida. Opções: {opcoes}")
        return f


# Instância única em memória, recarregável via /admin/reload
parametros = ParametrosFrete()


def carregar_parametros():
    global parametros
    novo_parametros = ParametrosFrete()
    novo_parametros.load()
    with _lock:
        parametros = novo_parametros


_UF_SIGLA_POR_NOME = {
    "acre": "AC", "alagoas": "AL", "amapá": "AP", "amazonas": "AM", "bahia": "BA",
    "ceará": "CE", "distrito federal": "DF", "espírito santo": "ES", "goiás": "GO",
    "maranhão": "MA", "mato grosso": "MT", "mato grosso do sul": "MS",
    "minas gerais": "MG", "pará": "PA", "paraíba": "PB", "paraná": "PR",
    "pernambuco": "PE", "piauí": "PI", "rio de janeiro": "RJ",
    "rio grande do norte": "RN", "rio grande do sul": "RS", "rondônia": "RO",
    "roraima": "RR", "santa catarina": "SC", "são paulo": "SP", "sergipe": "SE",
    "tocantins": "TO",
}


def _cidade_e_uf_da_retirada(endereco_resolvido: str) -> tuple[str | None, str]:
    """Extrai um provável nome de cidade (e a UF, quando identificável) a
    partir de um texto de endereço (resolvido pelo geocodificador, formato
    separado por vírgulas) ou de um nome de filial isolado (sem vírgula
    nenhuma, retorna ele mesmo sem UF).

    O Nominatim não tem um número fixo de segmentos entre a cidade e o
    país — endereços no Brasil costumam incluir "Região Geográfica
    Imediata/Intermediária de X" entre a cidade e o estado, e o CEP nem
    sempre aparece. Por isso descartamos, de trás pra frente, os
    segmentos reconhecíveis como país/CEP/UF/região, em vez de assumir
    uma posição fixa."""
    if not endereco_resolvido:
        return None, ""
    partes = [p.strip() for p in endereco_resolvido.split(",") if p.strip()]
    if len(partes) < 3:
        return (_sem_sufixo_uf(partes[0]) if partes else None), ""

    i = len(partes) - 1
    uf_consumida = False
    uf_sigla = ""
    while i > 0:
        seg = partes[i].strip().lower()
        if seg in ("brasil", "brazil"):
            i -= 1
        elif _CEP_SOLTO_REGEX.match(partes[i].strip()):
            i -= 1
        elif seg in _UFS_BR and not uf_consumida:
            # Só descarta a UF uma vez: capitais como São Paulo e Rio de
            # Janeiro têm o mesmo nome do estado, e a segunda ocorrência
            # (mais à esquerda) é a cidade, não o estado de novo.
            uf_consumida = True
            uf_sigla = _UF_SIGLA_POR_NOME.get(seg, "")
            i -= 1
        elif seg in _UFS_BR_SIGLAS and not uf_consumida:
            # Mesma ideia, mas pra quando a UF aparece como sigla em
            # segmento próprio (ex: "..., São Paulo, SP, Brasil").
            uf_consumida = True
            uf_sigla = partes[i].strip().upper()
            i -= 1
        elif seg.startswith("região") or seg.startswith("regiao"):
            i -= 1
        else:
            break
    return _sem_sufixo_uf(partes[i]), uf_sigla


def _cidade_da_retirada(endereco_resolvido: str) -> str | None:
    return _cidade_e_uf_da_retirada(endereco_resolvido)[0]


def cidade_e_uf(endereco_resolvido: str) -> tuple[str | None, str]:
    """Versão pública de :func:`_cidade_e_uf_da_retirada`, usada fora do
    cálculo de frete (ex: exportação de orçamento para planilha) para obter
    cidade + UF a partir de um endereço resolvido ou nome de filial."""
    return _cidade_e_uf_da_retirada(endereco_resolvido)


def _taxas_regionais_aplicaveis(
    p: "ParametrosFrete", cidade_origem: str | None, cidade_destino: str | None
) -> list[TaxaRegional]:
    """Retorna as taxas regionais cadastradas cuja cidade bate com a
    cidade de origem OU de destino do frete (comparação case-insensitive)
    — a cidade pode estar em qualquer posição da lista guardada na
    linha da taxa."""
    cidades_da_rota = set()
    for texto in (cidade_origem, cidade_destino):
        cidade = _cidade_da_retirada(texto) if texto else None
        if cidade:
            cidades_da_rota.add(db.normalizar_texto(cidade))
    if not cidades_da_rota:
        return []
    aplicaveis = []
    for t in p.taxas_regionais:
        cidades_taxa = {db.normalizar_texto(c) for c in db._dividir_cidades(t.cidade)}
        if cidades_da_rota & cidades_taxa:
            aplicaveis.append(t)
    return aplicaveis


CORINGA_ROTA = "*"  # cidade_origem/cidade_destino (e veiculo, na taxa de balsa) cadastrado como "*" casa com qualquer valor


def _campo_bate_curinga(cadastrado: str, valor: str) -> bool:
    return cadastrado == CORINGA_ROTA or cadastrado == valor


def _campo_bate_localidade(cadastrado: str, cidade: str, uf: str) -> bool:
    """Compara um campo cidade_destino cadastrado (taxa de balsa,
    distância fixa ou prioridade de rota) contra a cidade/UF resolvidas
    do frete. Além do curinga "*" (casa com qualquer) e do nome exato de
    cidade, aceita uma sigla de UF normalizada cadastrada no lugar da
    cidade — ex: "am" casa com Manaus, Manacapuru, Itacoatiara etc., sem
    precisar cadastrar uma linha por cidade do estado (ver
    _especificidade_localidade pra critério de desempate quando mais de
    uma linha bate)."""
    if cadastrado == CORINGA_ROTA:
        return True
    if cadastrado in _UFS_BR_SIGLAS:
        return bool(uf) and cadastrado == uf
    return cadastrado == cidade


def _especificidade_localidade(cadastrado: str) -> int:
    """Nível de especificidade de um campo cidade_destino pra desempate
    quando mais de uma linha cadastrada bate (ver _campo_bate_localidade):
    curinga "*" (0) é menos específico que uma sigla de UF (1), que por
    sua vez é menos específica que o nome exato de uma cidade (2) — uma
    exceção cadastrada pra uma cidade específica sempre vence a regra
    geral do estado ou do curinga total."""
    if cadastrado == CORINGA_ROTA:
        return 0
    if cadastrado in _UFS_BR_SIGLAS:
        return 1
    return 2


def _mais_especifica(candidatas: list[tuple[int, object]]):
    """Escolhe a linha cadastrada mais específica dentre as que bateram
    (maior especificidade, ver _especificidade_localidade) — ou None se
    não houver nenhuma candidata. Mesmo critério de desempate usado por
    _taxa_balsa_aplicavel, prioridade_rota_aplicavel,
    aliquota_icms_aplicavel e distancia_fixa_aplicavel."""
    if not candidatas:
        return None
    return max(candidatas, key=lambda par: par[0])[1]


def _normalizar_par_cidades(cidade_origem: str | None, cidade_destino: str | None) -> tuple[str, str, str] | None:
    """Extrai e normaliza (minúsculas, sem acento) a cidade de origem e
    destino de dois textos de endereço/filial, mais a UF do destino —
    usado pelas checagens de taxa de balsa/distância fixa direcionais
    (ver _campo_bate_localidade). Devolve None se alguma das duas cidades
    não puder ser identificada."""
    if not cidade_origem or not cidade_destino:
        return None
    cid_o = _cidade_da_retirada(cidade_origem)
    cid_d, uf_d = _cidade_e_uf_da_retirada(cidade_destino)
    if not cid_o or not cid_d:
        return None
    return db.normalizar_texto(cid_o), db.normalizar_texto(cid_d), db.normalizar_texto(uf_d)


def _taxa_balsa_aplicavel(
    p: "ParametrosFrete", cidade_origem: str | None, cidade_destino: str | None, veiculo: str
) -> TaxaBalsa | None:
    """Retorna a taxa de balsa cadastrada pra essa rota + veículo, se
    houver — direcional (cidade_origem -> cidade_destino nessa ordem
    exata): ida e volta são cotações independentes, então uma taxa
    cadastrada só pra A->B não se aplica automaticamente à rota B->A. O
    valor também pode variar por veículo (balsa cobra por categoria do
    veículo embarcado), então precisa bater o veículo escolhido também.

    Os três campos (cidade_origem, cidade_destino, veiculo) aceitam "*"
    como curinga — ex: uma travessia por corredor fluvial (Belém↔Manaus)
    vale pra praticamente qualquer origem no Brasil, sem precisar
    cadastrar uma linha por UF. Além disso, cidade_destino também aceita
    uma sigla de UF (ex: "AM") em vez do nome de uma cidade — casa com
    qualquer cidade daquele estado, não só a capital (ver
    _campo_bate_localidade). Quando mais de uma linha bate (ex: um
    curinga "*"→AM e uma exceção específica cadastrada pra uma origem
    que NÃO usa balsa naquele destino), vence a linha mais específica —
    cidade exata > UF > curinga (ver _especificidade_localidade)."""
    par = _normalizar_par_cidades(cidade_origem, cidade_destino)
    if par is None:
        return None
    cid_o, cid_d, uf_d = par
    veic = db.normalizar_texto(veiculo)
    candidatas = []
    for t in p.taxas_balsa:
        t_o, t_d, t_v = db.normalizar_texto(t.cidade_origem), db.normalizar_texto(t.cidade_destino), db.normalizar_texto(t.veiculo)
        if _campo_bate_curinga(t_o, cid_o) and _campo_bate_localidade(t_d, cid_d, uf_d) and _campo_bate_curinga(t_v, veic):
            especificidade = (t_o != CORINGA_ROTA) + _especificidade_localidade(t_d) + (t_v != CORINGA_ROTA)
            candidatas.append((especificidade, t))
    return _mais_especifica(candidatas)


def prioridade_rota_aplicavel(
    p: "ParametrosFrete", cidade_origem: str | None, cidade_destino: str | None
) -> PrioridadeRota | None:
    """Retorna a prioridade de rota cadastrada pra essa rota (estado_origem
    -> cidade_destino), se houver — usada por geo_service.calcular_distancia
    pra decidir se a distância do frete deve ser calculada em duas pernas
    (origem -> filial_escala + filial_escala -> destino) em vez da rota
    direta, quando o destino não tem acesso rodoviário direto da origem
    (ex: cargas para Manaus sempre passam por uma filial em Belém antes).

    A origem é comparada pela UF (não pela cidade exata): a regra
    normalmente vale pro estado inteiro de onde a carga sai, não só uma
    cidade específica. estado_origem aceita "*" como curinga; cidade_destino
    aceita "*", uma sigla de UF (ex: "AM" — casa com qualquer cidade do
    estado, não só a capital) ou o nome exato de uma cidade, mesmo
    mecanismo de _taxa_balsa_aplicavel (ver _campo_bate_localidade) —
    quando mais de uma linha bate, vence a mais específica."""
    if not cidade_origem or not cidade_destino:
        return None
    _, uf_origem = cidade_e_uf(cidade_origem)
    cid_d, uf_destino = _cidade_e_uf_da_retirada(cidade_destino)
    if not cid_d:
        return None
    uf_o, cid_d, uf_d = db.normalizar_texto(uf_origem), db.normalizar_texto(cid_d), db.normalizar_texto(uf_destino)
    candidatas = []
    for e in p.prioridades_rota:
        e_uf, e_d = db.normalizar_texto(e.estado_origem), db.normalizar_texto(e.cidade_destino)
        if _campo_bate_curinga(e_uf, uf_o) and _campo_bate_localidade(e_d, cid_d, uf_d):
            especificidade = (e_uf != CORINGA_ROTA) + _especificidade_localidade(e_d)
            candidatas.append((especificidade, e))
    return _mais_especifica(candidatas)


def destino_tem_prioridade_rota_cadastrada(p: "ParametrosFrete", cidade_destino: str | None) -> bool:
    """True se existe alguma Prioridade de Rota cadastrada pra essa cidade
    de destino (ou pro estado dela, ver _campo_bate_localidade), em
    qualquer estado de origem (ignora a UF de origem, ao contrário de
    prioridade_rota_aplicavel). Usada só por
    geo_service._buscar_rota_no_historico pra decidir se pode confiar numa
    distância reaproveitada do histórico: a prioridade pode ter sido
    cadastrada DEPOIS de uma cotação antiga já salva (ex: destino Manaus
    cotado antes de existir a escala obrigatória por Belém), e reaproveitar
    essa distância antiga às cegas manteria a rota errada (terrestre
    direta) pra sempre nas cotações seguintes."""
    if not cidade_destino:
        return False
    cid_d, uf_d = _cidade_e_uf_da_retirada(cidade_destino)
    if not cid_d:
        return False
    cid_d, uf_d = db.normalizar_texto(cid_d), db.normalizar_texto(uf_d)
    return any(
        _campo_bate_localidade(db.normalizar_texto(e.cidade_destino), cid_d, uf_d)
        for e in p.prioridades_rota
    )


def _uf_de_origem_ou_destino(p: "ParametrosFrete", texto: str | None) -> str:
    """UF de um texto de origem/destino de frete, que pode ser um endereço
    resolvido pelo geocodificador ("Cidade, Estado, Brasil", ver cidade_e_uf)
    ou só o nome de uma filial cadastrada (ex: quando a origem do orçamento é
    "Filial", o front manda só o nome, sem endereço completo — ver
    payload.cidade_origem em routers/orcamento.py). Nesse segundo caso, usa a
    UF cadastrada na própria filial (tabela filiais) em vez de tentar
    extrair da string do endereço: o endereço da filial normalmente é só
    rua/número/bairro/CEP (o nome da filial já é a "cidade de referência"),
    sem cidade/UF no texto, então cidade_e_uf não acharia nada nele.

    Terceiro caso: endereço digitado à mão no formato curto "Cidade, UF"
    (2 segmentos só) — cidade_e_uf exige 3+ segmentos (formato de
    geocodificador completo, ver seu docstring) e devolve UF vazia pra
    esse formato, então cai pra um fallback local aqui: se o último
    segmento separado por vírgula for exatamente uma sigla de UF
    reconhecida, usa ela direto."""
    if not texto:
        return ""
    filial = p.filiais.get(texto.strip().lower())
    if filial and filial.uf:
        return filial.uf
    _, uf = cidade_e_uf(texto)
    if uf:
        return uf
    ultimo_segmento = texto.rsplit(",", 1)[-1].strip().lower()
    return ultimo_segmento.upper() if ultimo_segmento in _UFS_BR_SIGLAS else ""


def _diaria_veiculo_aplicada(
    p: "ParametrosFrete",
    cidade_coleta: str | None,
    cidade_destino: str | None,
    distancia_coleta: float,
    coleta_terceirizada: bool,
    entrega_terceirizada: bool,
) -> tuple[float, dict | None]:
    """Diária de carreta + cavalo (ver taxas_diaria_veiculo) cobrada UMA
    ÚNICA VEZ por orçamento quando há retirada no cliente (coleta própria,
    não terceirizada) OU entrega no cliente (frota própria, não
    terceirizada) numa UF com diária cadastrada — mesmo que ambas batam ao
    mesmo tempo na mesma UF, não dobra o valor (é a mesma carreta/cavalo
    parados, não duas). Retirada e entrega são checadas cada uma na sua
    própria UF (não precisam ser a mesma) — a primeira UF cadastrada que
    bater entre as duas é usada."""
    if not p.taxas_diaria_veiculo:
        return 0.0, None
    retirada_no_cliente = not coleta_terceirizada and (distancia_coleta > 0 or bool(cidade_coleta))
    entrega_no_cliente = not entrega_terceirizada

    ufs_candidatas = []
    if retirada_no_cliente and cidade_coleta:
        uf = _uf_de_origem_ou_destino(p, cidade_coleta)
        if uf:
            ufs_candidatas.append(uf)
    if entrega_no_cliente and cidade_destino:
        uf = _uf_de_origem_ou_destino(p, cidade_destino)
        if uf:
            ufs_candidatas.append(uf)

    ufs_normalizadas = {db.normalizar_texto(uf) for uf in ufs_candidatas}
    for t in p.taxas_diaria_veiculo:
        if db.normalizar_texto(t.uf) in ufs_normalizadas:
            valor = t.valor_carreta + t.valor_cavalo
            return valor, {
                "uf": t.uf,
                "valor_carreta": t.valor_carreta,
                "valor_cavalo": t.valor_cavalo,
            }
    return 0.0, None


def aliquota_icms_aplicavel(
    p: "ParametrosFrete", cidade_origem: str | None, cidade_destino: str | None
) -> AliquotaIcms | None:
    """Retorna a alíquota de ICMS cadastrada pra rota estado_origem ->
    estado_destino, se houver — usada por calcular_orcamento pra aplicar o
    imposto "por dentro" (gross-up) sobre o frete_total. Ambos os lados são
    comparados pela UF (ver _uf_de_origem_ou_destino), e aceitam "*" como
    curinga, mesmo mecanismo de _taxa_balsa_aplicavel — quando mais de uma
    linha bate, vence a mais específica."""
    if not cidade_origem or not cidade_destino:
        return None
    uf_origem = _uf_de_origem_ou_destino(p, cidade_origem)
    uf_destino = _uf_de_origem_ou_destino(p, cidade_destino)
    if not uf_origem or not uf_destino:
        return None
    uf_o, uf_d = db.normalizar_texto(uf_origem), db.normalizar_texto(uf_destino)
    candidatas = []
    for a in p.aliquotas_icms:
        a_o, a_d = db.normalizar_texto(a.estado_origem), db.normalizar_texto(a.estado_destino)
        if _campo_bate_curinga(a_o, uf_o) and _campo_bate_curinga(a_d, uf_d):
            especificidade = (a_o != CORINGA_ROTA) + (a_d != CORINGA_ROTA)
            candidatas.append((especificidade, a))
    return _mais_especifica(candidatas)


def pedagio_rota_aplicavel(
    p: "ParametrosFrete", cidade_origem: str | None, cidade_destino: str | None, numero_eixos: int
) -> tuple[float, list[str]] | None:
    """Soma o pedágio das praças cadastradas (ver /admin/pracas-pedagio e
    /admin/pedagios-rota) pro corredor cidade_origem -> cidade_destino,
    direcional (mesma regra de _taxa_balsa_aplicavel: ida e volta são
    cotações independentes) e com o mesmo mecanismo de curinga "*" e
    especificidade -- mas, diferente de taxa de balsa, quando várias
    linhas de pedagios_rota batem no corredor mais específico, TODAS
    (não só uma) entram na soma: um corredor normalmente atravessa mais
    de uma praça.

    Devolve (total, [nomes das praças usadas]), ou None se não houver
    nenhum corredor cadastrado pra essa rota (deixa o chamador cair pra
    estimativa do Google/valor manual) ou se numero_eixos não tiver preço
    cadastrado em nenhuma das praças do corredor (0 é tratado como "não
    cadastrado", não como pedágio grátis)."""
    par = _normalizar_par_cidades(cidade_origem, cidade_destino)
    if par is None or numero_eixos <= 0:
        return None
    cid_o, cid_d, _uf_d = par
    candidatas = []
    for pr in p.pedagios_rota:
        pr_o, pr_d = db.normalizar_texto(pr.cidade_origem), db.normalizar_texto(pr.cidade_destino)
        if _campo_bate_curinga(pr_o, cid_o) and _campo_bate_curinga(pr_d, cid_d):
            especificidade = (pr_o != CORINGA_ROTA) + (pr_d != CORINGA_ROTA)
            candidatas.append((especificidade, pr))
    if not candidatas:
        return None
    maior_especificidade = max(especificidade for especificidade, _ in candidatas)
    vencedoras = [pr for especificidade, pr in candidatas if especificidade == maior_especificidade]

    total = 0.0
    pracas_usadas = []
    for pr in vencedoras:
        praca = p.pracas_pedagio.get(pr.praca_id)
        if praca is None:
            continue
        valor = praca.valores_por_eixo.get(numero_eixos) or 0
        if valor > 0:
            total += valor
            pracas_usadas.append(praca.nome)
    if not pracas_usadas:
        return None
    return round(total, 2), pracas_usadas


def distancia_fixa_aplicavel(
    p: "ParametrosFrete", cidade_origem: str | None, cidade_destino: str | None
) -> DistanciaFixa | None:
    """Retorna a distância fixa cadastrada (ver /admin/distancias-fixas)
    pro corredor cidade_origem -> cidade_destino, se houver — usada por
    geo_service pra sobrepor o cálculo automático (rodoviário via OSRM/
    Google) quando a rota real usada na prática é bem diferente (ex:
    trecho com travessia de balsa, mais curto que contornar de estrada
    — o cálculo automático não sabe considerar isso). Direcional; aceita
    "*", uma sigla de UF (ex: "AM" — casa com qualquer cidade do estado)
    ou o nome exato de uma cidade em cidade_destino, mesmo mecanismo de
    _taxa_balsa_aplicavel (ver _campo_bate_localidade); quando mais de
    uma linha bate, vence a mais específica."""
    par = _normalizar_par_cidades(cidade_origem, cidade_destino)
    if par is None:
        return None
    cid_o, cid_d, uf_d = par
    candidatas = []
    for df in p.distancias_fixas:
        df_o, df_d = db.normalizar_texto(df.cidade_origem), db.normalizar_texto(df.cidade_destino)
        if _campo_bate_curinga(df_o, cid_o) and _campo_bate_localidade(df_d, cid_d, uf_d):
            especificidade = (df_o != CORINGA_ROTA) + _especificidade_localidade(df_d)
            candidatas.append((especificidade, df))
    return _mais_especifica(candidatas)


def distancia_balsa_km(
    p: "ParametrosFrete", cidade_origem: str | None, cidade_destino: str | None, prioridade_rota: str | None,
) -> float:
    """Quantos km da distância total do frete correspondem a um trecho com
    distância fixa cadastrada (travessia de balsa, ver
    distancia_fixa_aplicavel) — usado por calcular_orcamento pra excluir
    esse trecho do cálculo de custo_km/custo_manutencao (tarifa por km
    rodado). O veículo não roda esse trecho, vai de balsa: cobrar tarifa
    de estrada por cima dele, além da taxa de balsa (custo_balsa) já
    cadastrada pra essa rota, cobraria a mesma travessia duas vezes.

    Quando o frete passou por uma Prioridade de Rota (escala obrigatória,
    ex: destino Manaus via filial em Belém — prioridade_rota traz o nome
    dessa filial), a distância fixa é checada na perna filial->destino,
    não na rota origem->destino inteira. Sem prioridade de rota, checa a
    rota direta."""
    fixa = (
        distancia_fixa_aplicavel(p, prioridade_rota, cidade_destino) if prioridade_rota
        else distancia_fixa_aplicavel(p, cidade_origem, cidade_destino)
    )
    return fixa.distancia_km if fixa else 0.0


def _prazo_estimado_dias_uteis(distancia_rodoviaria: float, balsa_km: float) -> int:
    """Prazo estimado (dias úteis) pela distância rodoviária real da rota
    -- 1 dia base + 1 dia adicional a cada PRAZO_KM_POR_DIA_ADICIONAL km
    (distancia_rodoviaria já exclui o trecho de balsa, ver balsa_km em
    calcular_orcamento/calcular_orcamento_fracionado), mais
    PRAZO_DIAS_EXTRA_BALSA(_SECA) dias quando a rota tem travessia de
    balsa -- substitui o SLA.prazo_dias fixo (que não varia por rota, ver
    achado #7 do Teste_Completo_FTL_2026_Sistema_vs_Planilha.xlsx)."""
    dias = 1 + int(distancia_rodoviaria // PRAZO_KM_POR_DIA_ADICIONAL)
    if balsa_km > 0:
        mes_atual = datetime.date.today().month
        dias += PRAZO_DIAS_EXTRA_BALSA_SECA if mes_atual in _MESES_SECA_BALSA else PRAZO_DIAS_EXTRA_BALSA
    return dias


def _custo_lotacao_destino_aplicavel(
    p: "ParametrosFrete", cidade_origem: str | None, cidade_destino: str | None,
) -> float | None:
    """Custo operacional (R$) pré-tabelado pra uma rota de lotação (FTL)
    fechada, porta-a-porta, cadastrado em custos_lotacao_destino por
    origem (UF, ver _uf_de_origem_ou_destino) e cidade/UF de destino --
    mesma lógica da planilha legada (tabela de custo por rota, não por
    km rodado). Devolve None quando a UF de origem não tem nenhuma rota
    cadastrada ainda, ou quando a cidade/UF de destino dessa origem não
    está na tabela -- nesses casos calcular_orcamento cai no fallback de
    tarifa_km*distância normal."""
    if not p.custos_lotacao_destino:
        return None
    origem_tabela = _uf_de_origem_ou_destino(p, cidade_origem)
    if not origem_tabela:
        return None
    cidade_dest = _cidade_da_retirada(cidade_destino) if cidade_destino else None
    # cidade_e_uf exige 3+ segmentos (formato completo do geocodificador,
    # ver seu docstring) -- pro formato curto "Cidade, UF" (2 segmentos,
    # comum em endereço digitado à mão), usa o mesmo fallback robusto que
    # _uf_de_origem_ou_destino já tem em vez de cidade_e_uf direto.
    uf_dest = _uf_de_origem_ou_destino(p, cidade_destino) if cidade_destino else ""
    if not cidade_dest or not uf_dest:
        return None
    chave = (origem_tabela, uf_dest, db.normalizar_texto(cidade_dest))
    return p.custos_lotacao_destino.get(chave)


def _classificar_capital_interior(p: "ParametrosFrete", uf_destino: str, cidade_destino: str) -> str:
    """'CAPITAL' quando a cidade (normalizada) está em CAPITAIS_BR pra essa
    UF, senão 'INTERIOR' -- ver _custo_fracionado_destino_aplicavel. Exceção
    conhecida: a Bahia tem três faixas na planilha ('CAPITAL'/'INTERIOR I'/
    'INTERIOR II') em vez de duas; como CAPITAIS_BR só distingue capital x
    resto, cidades do interior da Bahia caem todas em 'INTERIOR', e
    _custo_fracionado_destino_aplicavel tenta 'INTERIOR I' como variante
    quando 'INTERIOR' não está cadastrado pra essa UF -- não diferencia
    I de II, limitação conhecida e documentada aqui."""
    cidade_norm = db.normalizar_texto(cidade_destino)
    if cidade_norm in CAPITAIS_BR.get(uf_destino.strip().upper(), set()):
        return "CAPITAL"
    return "INTERIOR"


def _custo_fracionado_destino_aplicavel(
    p: "ParametrosFrete", cidade_origem: str | None, cidade_destino: str | None, peso_considerado: float,
) -> float | None:
    """Custo operacional (R$) do Fracionado (LTL) pré-tabelado por faixa de
    peso, somando os 3 componentes (coleta + embarque + entrega)
    cadastrados em custos_fracionado_destino pra essa origem (UF da tabela,
    ver _uf_de_origem_ou_destino -- só 'SP' e 'AM' têm tabela extraída hoje)
    e cidade/UF de destino -- mesma lógica das abas "TB FRACIONADO - CUSTO"
    da planilha legada. Devolve None quando a origem não tem tabela
    cadastrada, ou quando falta QUALQUER um dos 3 componentes pra esse
    destino (a planilha não tem embarque/entrega cadastrados pra toda UF a
    partir de toda origem) -- nesses casos calcular_orcamento_fracionado
    cai no fallback de faixas_peso_fracionado/faixas_distancia_fracionado
    genérico."""
    if not p.custos_fracionado_destino:
        return None
    origem_tabela = _uf_de_origem_ou_destino(p, cidade_origem)
    if not origem_tabela:
        return None
    cidade_dest = _cidade_da_retirada(cidade_destino) if cidade_destino else None
    uf_dest = _uf_de_origem_ou_destino(p, cidade_destino) if cidade_destino else ""
    if not cidade_dest or not uf_dest:
        return None
    capital_interior = _classificar_capital_interior(p, uf_dest, cidade_dest)
    total = 0.0
    for componente in ("coleta", "embarque", "entrega"):
        faixa = p.custos_fracionado_destino.get((origem_tabela, uf_dest, capital_interior, componente))
        if faixa is None and capital_interior == "INTERIOR":
            # Bahia: a planilha não tem faixa "INTERIOR" simples, só
            # "INTERIOR I"/"INTERIOR II" -- usa "INTERIOR I" como
            # aproximação (ver docstring de _classificar_capital_interior).
            faixa = p.custos_fracionado_destino.get((origem_tabela, uf_dest, "INTERIOR I", componente))
        if faixa is None:
            return None
        total += faixa.calcular(peso_considerado)
    return total


def _prazo_fracionado_destino_aplicavel(
    p: "ParametrosFrete", cidade_origem: str | None, cidade_destino: str | None,
) -> int | None:
    """Prazo (dias úteis) do Fracionado (LTL) pré-tabelado por destino,
    cadastrado em prazo_fracionado_destino -- diferente da Lotação, cujo
    prazo é calculado por distância (_prazo_estimado_dias_uteis), o prazo
    real do Fracionado não varia com km rodado: varia com a classificação
    do destino (UF + capital/interior), confirmado em cotações reais da
    planilha legada (ver CONTEXTO.md). Devolve None quando a origem não
    tem tabela cadastrada ou não há entrada pra esse destino -- nesse
    caso calcular_orcamento_fracionado cai no fallback de
    _prazo_estimado_dias_uteis (fórmula por km, validada só pra
    Lotação)."""
    if not p.prazo_fracionado_destino:
        return None
    origem_tabela = _uf_de_origem_ou_destino(p, cidade_origem)
    if not origem_tabela:
        return None
    cidade_dest = _cidade_da_retirada(cidade_destino) if cidade_destino else None
    uf_dest = _uf_de_origem_ou_destino(p, cidade_destino) if cidade_destino else ""
    if not cidade_dest or not uf_dest:
        return None
    capital_interior = _classificar_capital_interior(p, uf_dest, cidade_dest)
    dias = p.prazo_fracionado_destino.get((origem_tabela, uf_dest, capital_interior))
    if dias is None and capital_interior == "INTERIOR":
        # Bahia: mesma aproximação de _custo_fracionado_destino_aplicavel
        # (a planilha não tem faixa "INTERIOR" simples pra esse estado).
        dias = p.prazo_fracionado_destino.get((origem_tabela, uf_dest, "INTERIOR I"))
    return dias


def _taxa_balsa_outros_veiculos(
    p: "ParametrosFrete", cidade_origem: str | None, cidade_destino: str | None, veiculo_atual: str
) -> list[str]:
    """Veículos (diferentes do escolhido no orçamento) que têm taxa de
    balsa cadastrada pra essa mesma rota direcional — só um diagnóstico
    pra memória de cálculo avisar quando a rota bateu mas o veículo não,
    em vez de zerar o custo de balsa silenciosamente."""
    par = _normalizar_par_cidades(cidade_origem, cidade_destino)
    if par is None:
        return []
    cid_o, cid_d, uf_d = par
    veic_atual = db.normalizar_texto(veiculo_atual)
    encontrados = {
        t.veiculo for t in p.taxas_balsa
        if _campo_bate_curinga(db.normalizar_texto(t.cidade_origem), cid_o)
        and _campo_bate_localidade(db.normalizar_texto(t.cidade_destino), cid_d, uf_d)
        and db.normalizar_texto(t.veiculo) != veic_atual
    }
    return sorted(encontrados)


@dataclass
class SelecaoVeiculo:
    veiculo: Veiculo
    volume_total_m3: float
    peso_cubado: float
    peso_considerado: float


def _calcular_cubagem(peso: float, paletes: list[dict], transp: Transporte) -> tuple[float, float, float]:
    """Volume total (m³), peso cubado e peso considerado (maior entre real
    e cubado) — parte de escolher_veiculo que não depende de escolher
    veículo nenhum, reaproveitada por calcular_orcamento_fracionado (que
    não escolhe veículo pelo peso, o veículo lá é informado direto)."""
    # quantidade (padrão 1) deixa cadastrar "3 paletes iguais" numa linha
    # só, em vez de repetir a mesma linha 3 vezes — cada um conta seu
    # volume individual multiplicado pela quantidade.
    volume_total_cm3 = sum(
        pal["comprimento"] * pal["largura"] * pal["altura"] * pal.get("quantidade", 1) for pal in paletes
    )
    volume_total_m3 = volume_total_cm3 / 1_000_000
    # Padrão de mercado: fator_cubagem é em kg/m³ (ex: 300 rodoviário, 167
    # aéreo — o mesmo valor padrão IATA), multiplicado pelo volume em m³.
    peso_cubado = volume_total_m3 * transp.fator_cubagem
    peso_considerado = max(peso, peso_cubado)
    return volume_total_m3, peso_cubado, peso_considerado


def escolher_veiculo(peso: float, paletes: list[dict], transp: Transporte) -> SelecaoVeiculo:
    """Mesma lógica de escolha de veículo usada em calcular_orcamento
    (peso real x peso cubado, dentro da capacidade em m³) — extraída pra
    função própria porque geo_service também precisa saber qual veículo
    seria escolhido, antes mesmo de calcular o orçamento (usada pra achar
    uma rota já cotada no histórico com o mesmo veículo, ver
    geo_service._buscar_rota_no_historico)."""
    volume_total_m3, peso_cubado, peso_considerado = _calcular_cubagem(peso, paletes, transp)
    veiculo = parametros.buscar_veiculo_por_peso_e_volume(peso_considerado, volume_total_m3)
    return SelecaoVeiculo(veiculo, volume_total_m3, peso_cubado, peso_considerado)


# ============================================================
# Taxas/impostos/margem compartilhados entre calcular_orcamento e
# calcular_orcamento_fracionado — tudo que roda depois do frete_ajustado
# ser calculado (a parte que difere entre os dois: escolha de veículo x
# faixas de peso/distância) e é idêntico nas duas contas. Cada helper
# reflete exatamente o mesmo cálculo, na mesma ordem, que antes vivia
# duplicado nas duas funções.
# ============================================================


def _custos_extras_aplicados(custos_extras: list[dict]) -> tuple[list[dict], float]:
    """Detalha e soma os custos extras escolhidos no orçamento (categoria +
    valor em R$ digitado por quem cota) — diferente das taxas adicionais
    abaixo, não vem de um catálogo com valor pré-cadastrado."""
    detalhe_custos_extras = []
    custo_extra_total = 0.0
    for custo_extra in custos_extras:
        valor_aplicado = round(custo_extra.get("valor", 0), 2)
        custo_extra_total += valor_aplicado
        detalhe_custos_extras.append({"categoria": custo_extra["categoria"], "valor_aplicado": valor_aplicado})
    return detalhe_custos_extras, custo_extra_total


def _piso_taxa_customizavel(p: "ParametrosFrete", nome: str) -> float:
    """% mínimo (piso) pra um campo de taxa adicional digitável por
    orçamento (GRIS, Ad Valorem, ver _NOME_TAXA_GRIS/_NOME_TAXA_AD_VALOREM)
    -- o % cadastrado em Tabela de Preços pra essa taxa (0 se não houver
    nenhuma cadastrada com esse nome). Não chame pra uma taxa cadastrada
    como 'fixo' (ver _taxa_customizavel_e_tipo_fixo primeiro) -- % e R$
    fixo não são comparáveis, então esse piso não faz sentido nesse caso."""
    chave = nome.strip().lower()
    for taxa in p.taxas_adicionais:
        if taxa.nome.strip().lower() == chave:
            return taxa.valor
    return 0.0


def _taxa_customizavel_e_tipo_fixo(p: "ParametrosFrete", nome: str) -> bool:
    """True se já existe uma taxa cadastrada com esse nome (GRIS, Ad
    Valorem) do tipo 'fixo' (R$, não %) — nesse caso o campo digitável por
    orçamento (sempre um %, ver gris_pct/ad_valorem_pct) não tem como
    garantir que o resultado nunca fique abaixo do valor cadastrado (bases
    diferentes: % do valor da mercadoria vs. R$ fixo independente dele),
    então a substituição é bloqueada — só é permitida quando a taxa
    cadastrada é 'percentual' ou quando não há nenhuma com esse nome."""
    chave = nome.strip().lower()
    for taxa in p.taxas_adicionais:
        if taxa.nome.strip().lower() == chave:
            return taxa.tipo != "percentual"
    return False


def _taxas_adicionais_aplicadas(
    p: "ParametrosFrete", valor_mercadoria: float,
    gris_pct: float | None = None, ad_valorem_pct: float | None = None,
) -> tuple[list[dict], float]:
    """Taxas adicionais cadastradas (fixas em R$ ou % do valor da
    mercadoria) — entram sempre, sem depender de rota. GRIS e Ad Valorem
    são digitáveis por orçamento: quando gris_pct/ad_valorem_pct vêm
    informados (não None — já validados contra o piso cadastrado em
    calcular_orcamento), o % digitado substitui o % cadastrado de mesmo
    nome; sem override, usa o cadastrado normalmente. Um override sem
    nenhuma taxa cadastrada de mesmo nome ainda assim entra no cálculo,
    como uma taxa avulsa desse orçamento (piso 0%, ver
    _piso_taxa_customizavel)."""
    overrides = {_NOME_TAXA_GRIS.lower(): gris_pct, _NOME_TAXA_AD_VALOREM.lower(): ad_valorem_pct}
    detalhe_taxas = []
    custo_taxas_adicionais = 0.0
    aplicados = set()
    for taxa in p.taxas_adicionais:
        chave = taxa.nome.strip().lower()
        override = overrides.get(chave)
        if override is not None:
            valor_configurado = override
            valor_taxa = valor_mercadoria * (override / 100)
            aplicados.add(chave)
        else:
            valor_configurado = taxa.valor
            valor_taxa = _valor_taxa(taxa.tipo, taxa.valor, valor_mercadoria)
        custo_taxas_adicionais += valor_taxa
        detalhe_taxas.append({
            "nome": taxa.nome, "tipo": taxa.tipo,
            "valor_configurado": valor_configurado, "valor_aplicado": round(valor_taxa, 2),
        })
    for nome_exibicao, chave in ((_NOME_TAXA_GRIS, _NOME_TAXA_GRIS.lower()), (_NOME_TAXA_AD_VALOREM, _NOME_TAXA_AD_VALOREM.lower())):
        override = overrides.get(chave)
        if override is not None and chave not in aplicados:
            valor_taxa = valor_mercadoria * (override / 100)
            custo_taxas_adicionais += valor_taxa
            detalhe_taxas.append({
                "nome": nome_exibicao, "tipo": "percentual",
                "valor_configurado": override, "valor_aplicado": round(valor_taxa, 2),
            })
    return detalhe_taxas, custo_taxas_adicionais


def _taxas_regionais_aplicadas(
    p: "ParametrosFrete", cidade_origem: str | None, cidade_destino: str | None, valor_mercadoria: float,
) -> tuple[list[dict], float]:
    """Taxas regionais cuja cidade bate com origem ou destino do frete (ex:
    taxa de zona franca em Manaus, taxa de área de risco etc.)."""
    detalhe_taxas_regionais = []
    custo_taxas_regionais = 0.0
    for taxa in _taxas_regionais_aplicaveis(p, cidade_origem, cidade_destino):
        valor_taxa = _valor_taxa(taxa.tipo, taxa.valor, valor_mercadoria)
        custo_taxas_regionais += valor_taxa
        detalhe_taxas_regionais.append({
            "nome": taxa.nome, "cidade": taxa.cidade, "tipo": taxa.tipo,
            "valor_configurado": taxa.valor, "valor_aplicado": round(valor_taxa, 2),
        })
    return detalhe_taxas_regionais, custo_taxas_regionais


def _taxa_balsa_aplicada(
    p: "ParametrosFrete", cidade_origem: str | None, cidade_destino: str | None,
    veiculo_nome: str, valor_mercadoria: float,
) -> tuple[float, dict | None, list[str]]:
    """Custo de travessia de balsa pra rota + veículo do orçamento, se
    cadastrada — direcional (cidade_origem -> cidade_destino nessa ordem
    exata): ida e volta são cotações independentes, porque o preço da
    balsa pode ser diferente em cada sentido. Devolve (custo_balsa,
    detalhe_balsa, balsa_outro_veiculo); balsa_outro_veiculo lista
    veículos com taxa cadastrada pra essa mesma rota, quando ela bateu mas
    não pro veículo escolhido — avisa na memória de cálculo em vez de só
    zerar silenciosamente."""
    custo_balsa = 0.0
    detalhe_balsa = None
    balsa_outro_veiculo = []
    taxa_balsa = _taxa_balsa_aplicavel(p, cidade_origem, cidade_destino, veiculo_nome)
    if taxa_balsa:
        custo_balsa = _valor_taxa(taxa_balsa.tipo, taxa_balsa.valor, valor_mercadoria)
        detalhe_balsa = {
            "cidade_origem": taxa_balsa.cidade_origem, "cidade_destino": taxa_balsa.cidade_destino,
            "veiculo": taxa_balsa.veiculo, "tipo": taxa_balsa.tipo,
            "valor_configurado": taxa_balsa.valor, "valor_aplicado": round(custo_balsa, 2),
        }
    else:
        balsa_outro_veiculo = _taxa_balsa_outros_veiculos(p, cidade_origem, cidade_destino, veiculo_nome)
    return custo_balsa, detalhe_balsa, balsa_outro_veiculo


def _pedagio_aplicado(
    p: "ParametrosFrete", cidade_origem: str | None, cidade_destino: str | None,
    numero_eixos: int, base_sem_pedagio: float, pedagio_informado: float,
) -> tuple[float, bool, list[str] | None]:
    """Valor de pedágio a cobrar: quando há praça cadastrada pro corredor
    da rota + eixos do veículo (ver pedagio_rota_aplicavel), usa o valor
    informado (pré-preenchido na busca de distância a partir dessas
    praças, editável). Sem praça cadastrada, ignora o valor informado
    (estimativa genérica do Google Maps, ou manual) e aplica
    PEDAGIO_PCT_FALLBACK% sobre frete + custos operacionais + taxas (
    base_sem_pedagio, já soma tudo isso -- ver calcular_orcamento/
    calcular_orcamento_fracionado) COM PIS/COFINS e ICMS previstos por
    cima (sem margem, que só entra depois do pedágio já somado ao custo da
    operação). Essa é só uma pré-visualização de impostos pra dimensionar
    o pedágio -- ele entra no fluxo normal em seguida e volta a ser
    tributado de verdade (PIS/COFINS -> margem -> ICMS) junto com os
    demais custos. Devolve (pedagio, veio_de_estimativa_pct, praças
    usadas quando veio de cadastro)."""
    achado = pedagio_rota_aplicavel(p, cidade_origem, cidade_destino, numero_eixos)
    if achado is not None:
        _total, pracas_usadas = achado
        return pedagio_informado, False, pracas_usadas
    base_com_impostos, *_ = _aplicar_pis_cofins(p, base_sem_pedagio)
    base_com_impostos, *_ = _aplicar_icms(p, base_com_impostos, cidade_origem, cidade_destino)
    return round(base_com_impostos * PEDAGIO_PCT_FALLBACK / 100, 2), True, None


def _aplicar_pis_cofins(p: "ParametrosFrete", frete_total: float) -> tuple[float, float, float, float]:
    """PIS/COFINS: um percentual simples somado por fora sobre o
    frete_total apurado até aqui (custo da operação + impostos/taxas,
    ainda sem margem de lucro nem ICMS), com alíquota federal única (não
    varia por UF, ver ParametrosFrete.aliquota_pis_cofins) — aplicado
    ANTES da margem e do ICMS. Devolve (frete_total_novo,
    frete_sem_pis_cofins, valor_pis_cofins, aliquota_pis_cofins_pct)."""
    frete_sem_pis_cofins = frete_total
    valor_pis_cofins = 0.0
    aliquota_pis_cofins_pct = p.aliquota_pis_cofins
    if aliquota_pis_cofins_pct > 0:
        valor_pis_cofins = frete_sem_pis_cofins * (aliquota_pis_cofins_pct / 100)
        frete_total = frete_sem_pis_cofins + valor_pis_cofins
    return frete_total, frete_sem_pis_cofins, valor_pis_cofins, aliquota_pis_cofins_pct


def _aplicar_icms(
    p: "ParametrosFrete", frete_total: float, cidade_origem: str | None, cidade_destino: str | None,
) -> tuple[float, float, float, "AliquotaIcms | None", float]:
    """ICMS "por dentro" (gross-up), igual ao PIS/COFINS, somado por
    último, depois da margem de lucro já embutida em frete_total — a
    alíquota da rota (UF origem -> UF destino, ver aliquota_icms_aplicavel)
    incide sobre o valor total já cobrado do cliente (frete_total já com
    ICMS embutido), não é um acréscimo simples sobre o valor sem ICMS.
    Devolve (frete_total_novo, frete_sem_icms, valor_icms, icms_aplicavel,
    aliquota_icms_pct)."""
    frete_sem_icms = frete_total
    valor_icms = 0.0
    icms_aplicavel = aliquota_icms_aplicavel(p, cidade_origem, cidade_destino)
    aliquota_icms_pct = icms_aplicavel.aliquota if icms_aplicavel else 0.0
    if aliquota_icms_pct > 0:
        if aliquota_icms_pct >= 100:
            raise FreteConfigError(
                f"Alíquota de ICMS cadastrada ({aliquota_icms_pct}%) inválida — deve ser menor que 100%."
            )
        frete_total = frete_sem_icms / (1 - aliquota_icms_pct / 100)
        valor_icms = frete_total - frete_sem_icms
    return frete_total, frete_sem_icms, valor_icms, icms_aplicavel, aliquota_icms_pct


def _aplicar_margem_lucro(
    frete_total: float, total_custo_operacao: float, margem_lucro_pct: float
) -> tuple[float, float, float]:
    """Margem de lucro — valor fixo em R$ (margem_lucro_pct% do custo da
    operação, NÃO um markup percentual sobre impostos/taxas/PIS-COFINS/
    ICMS) somado por ÚLTIMO, depois de PIS/COFINS e ICMS já embutidos: a
    margem é a última camada antes do preço final cobrado do cliente, mas
    sua base de cálculo é só o custo da operação (ver total_custo_operacao
    em calcular_orcamento/calcular_orcamento_fracionado), não o frete_total
    corrente. Devolve (frete_total_novo, frete_sem_margem_lucro,
    valor_margem_lucro)."""
    frete_sem_margem_lucro = frete_total
    valor_margem_lucro = total_custo_operacao * (margem_lucro_pct / 100)
    frete_total = frete_sem_margem_lucro + valor_margem_lucro
    return frete_total, frete_sem_margem_lucro, valor_margem_lucro


def _aplicar_piso_markup(
    frete_total: float, total_impostos_taxas: float, base_piso: float
) -> tuple[float, float, float]:
    """Garante que o frete_total final (já com PIS/COFINS, ICMS e margem
    de lucro aplicados) seja pelo menos MARKUP_MINIMO vezes base_piso
    (custo da operação + impostos/taxas ORIGINAIS, antes de qualquer
    imposto ou margem, ver calcular_orcamento). Se ficar abaixo, a
    diferença é somada direto na linha de impostos/taxas e no
    frete_total — sem passar de novo por PIS/COFINS/ICMS (o ajuste entra
    depois deles, não antes). Devolve (frete_total_novo,
    total_impostos_taxas_novo, ajuste_piso_markup) — ajuste é 0 quando o
    frete_total já bate o piso sozinho."""
    piso = base_piso * MARKUP_MINIMO
    ajuste_piso_markup = max(0.0, piso - frete_total)
    if ajuste_piso_markup > 0:
        frete_total += ajuste_piso_markup
        total_impostos_taxas += ajuste_piso_markup
    return frete_total, total_impostos_taxas, ajuste_piso_markup


def calcular_orcamento(
    peso: float,
    paletes: list[dict],
    distancia: float,
    valor_mercadoria: float,
    categoria: str,
    transporte: str,
    sla: str,
    distancia_coleta: float = 0,
    cidade_coleta: str | None = None,
    cidade_origem: str | None = None,
    cidade_destino: str | None = None,
    coleta_terceirizada: bool = False,
    transportadora_coleta_nome: str = "",
    valor_coleta_terceirizada: float = 0,
    entrega_terceirizada: bool = False,
    transportadora_entrega_nome: str = "",
    valor_entrega_terceirizada: float = 0,
    pedagio: float = 0,
    distancia_retorno: float = 0,
    filial_retorno: str | None = None,
    prioridade_rota: str | None = None,
    custos_extras: list[dict] | None = None,
    gris_pct: float | None = None,
    ad_valorem_pct: float | None = None,
) -> dict:
    if peso <= 0:
        raise FreteInputError("Peso deve ser maior que zero.")
    if not paletes:
        raise FreteInputError("Informe ao menos um palete com comprimento, largura e altura.")
    for palete in paletes:
        if palete["comprimento"] <= 0 or palete["largura"] <= 0 or palete["altura"] <= 0:
            raise FreteInputError("Comprimento, largura e altura de cada palete devem ser maiores que zero.")
        if palete.get("quantidade", 1) < 1:
            raise FreteInputError("A quantidade de cada palete deve ser pelo menos 1.")
    if distancia <= 0:
        raise FreteInputError("Distância deve ser maior que zero.")
    if distancia_coleta < 0:
        raise FreteInputError("Distância de coleta não pode ser negativa.")
    if valor_mercadoria < 0:
        raise FreteInputError("Valor da mercadoria não pode ser negativo.")
    if valor_coleta_terceirizada < 0:
        raise FreteInputError("Valor da coleta terceirizada não pode ser negativo.")
    if valor_entrega_terceirizada < 0:
        raise FreteInputError("Valor da entrega terceirizada não pode ser negativo.")
    if pedagio < 0:
        raise FreteInputError("Valor de pedágio não pode ser negativo.")
    if distancia_retorno < 0:
        raise FreteInputError("Distância de retorno não pode ser negativa.")
    if gris_pct is not None:
        if _taxa_customizavel_e_tipo_fixo(parametros, _NOME_TAXA_GRIS):
            raise FreteInputError(
                "GRIS está cadastrado como valor fixo em Tabela de Preços — não é possível substituir por "
                "um % digitado nesse orçamento."
            )
        piso_gris = _piso_taxa_customizavel(parametros, _NOME_TAXA_GRIS)
        if gris_pct < piso_gris:
            raise FreteInputError(f"GRIS ({gris_pct}%) abaixo do mínimo cadastrado ({piso_gris}%).")
    if ad_valorem_pct is not None:
        if _taxa_customizavel_e_tipo_fixo(parametros, _NOME_TAXA_AD_VALOREM):
            raise FreteInputError(
                "Ad Valorem está cadastrado como valor fixo em Tabela de Preços — não é possível substituir "
                "por um % digitado nesse orçamento."
            )
        piso_ad_valorem = _piso_taxa_customizavel(parametros, _NOME_TAXA_AD_VALOREM)
        if ad_valorem_pct < piso_ad_valorem:
            raise FreteInputError(f"Ad Valorem ({ad_valorem_pct}%) abaixo do mínimo cadastrado ({piso_ad_valorem}%).")
    custos_extras = custos_extras or []
    for custo_extra in custos_extras:
        if custo_extra.get("categoria") not in CATEGORIAS_CUSTO_EXTRA:
            opcoes = ", ".join(CATEGORIAS_CUSTO_EXTRA)
            raise FreteInputError(
                f"Categoria de custo extra '{custo_extra.get('categoria')}' inválida. Opções: {opcoes}"
            )
        if custo_extra.get("valor", 0) < 0:
            raise FreteInputError("Valor de custo extra não pode ser negativo.")

    p = parametros
    transp = p.buscar_transporte(transporte)
    cat = p.buscar_categoria(categoria)
    s = p.buscar_sla(sla)

    selecao = escolher_veiculo(peso, paletes, transp)
    v = selecao.veiculo
    volume_total_m3 = selecao.volume_total_m3
    peso_cubado = selecao.peso_cubado
    peso_considerado = selecao.peso_considerado

    # Km com travessia de balsa (ver distancia_balsa_km) não é rodado pelo
    # veículo -- não entra na tarifa por km (nem na faixa que a determina)
    # nem na manutenção, senão a travessia seria cobrada duas vezes: uma
    # aqui como se fosse estrada, outra como custo_balsa mais abaixo.
    balsa_km = distancia_balsa_km(p, cidade_origem, cidade_destino, prioridade_rota)
    distancia_faturavel = max(distancia - balsa_km, 0.0)

    tarifa_km_usada, faixa_km_aplicada = p.tarifa_km_efetiva(v, distancia_faturavel)
    custo_km = tarifa_km_usada * distancia_faturavel
    # Peso excedente = quanto o peso considerado passa do "até" (limite
    # superior) da faixa do próprio veículo escolhido — normalmente é
    # zero, porque o veículo já foi escolhido pra cobrir esse peso
    # (buscar_veiculo_por_peso). Só fica positivo quando a carga
    # ultrapassa até o maior veículo cadastrado: nesse caso
    # buscar_veiculo_por_peso já devolve esse maior veículo mesmo assim
    # (fallback), e valor_tonelada_excedente funciona como sobretaxa de
    # sobrepeso pelas toneladas que passaram da capacidade máxima
    # disponível (valor cadastrado é por TONELADA, não por kg).
    peso_excedente = max(peso_considerado - v.ate, 0)
    custo_peso_excedente = (peso_excedente / 1000) * v.valor_tonelada_excedente

    # Rota com custo pré-tabelado (ver _custo_lotacao_destino_aplicavel)
    # substitui custo_km/custo_peso_excedente inteiramente pelo custo
    # operacional cadastrado + TAXA_FIXA_LOTACAO_TABELA -- sem rota
    # cadastrada, mantém o cálculo por tarifa_km*distância normal.
    custo_tabela_lotacao_destino = _custo_lotacao_destino_aplicavel(p, cidade_origem, cidade_destino)
    if custo_tabela_lotacao_destino is not None:
        # Valor já é o custo operacional completo porta-a-porta (mesma
        # lógica da planilha legada, que não tem conceito de categoria/
        # transporte/SLA) -- multiplicador_categoria/transporte/sla NÃO
        # se aplicam aqui: aplicá-los infacionaria silenciosamente um
        # valor que deveria ser exato, dependendo do que estiver
        # cadastrado em Tabela de Preços pra essa categoria/transporte/sla.
        frete_base = custo_tabela_lotacao_destino + TAXA_FIXA_LOTACAO_TABELA
        frete_ajustado = frete_base
    else:
        frete_base = custo_km + custo_peso_excedente
        frete_ajustado = frete_base * cat.multiplicador * transp.multiplicador * s.multiplicador

    detalhe_custos_extras, custo_extra_total = _custos_extras_aplicados(custos_extras)
    detalhe_taxas, custo_taxas_adicionais = _taxas_adicionais_aplicadas(p, valor_mercadoria, gris_pct, ad_valorem_pct)
    detalhe_taxas_regionais, custo_taxas_regionais = _taxas_regionais_aplicadas(
        p, cidade_origem, cidade_destino, valor_mercadoria
    )
    custo_balsa, detalhe_balsa, balsa_outro_veiculo = _taxa_balsa_aplicada(
        p, cidade_origem, cidade_destino, v.nome, valor_mercadoria
    )
    # Retorno vazio (destino -> filial de retorno) é uma travessia
    # independente da ida: taxa de balsa é direcional (ver
    # _taxa_balsa_aplicavel), então precisa da própria checagem, não
    # reaproveita detalhe_balsa acima. Quando bate uma taxa cadastrada
    # pra esse sentido, cobra ela — a balsa é cobrada sempre que a rota
    # passa por ela, ida ou volta — e o trecho já não roda por estrada
    # (ver distancia_retorno_faturavel abaixo).
    custo_balsa_retorno, detalhe_balsa_retorno = 0.0, None
    if distancia_retorno > 0 and filial_retorno:
        custo_balsa_retorno, detalhe_balsa_retorno, _ = _taxa_balsa_aplicada(
            p, cidade_destino, filial_retorno, v.nome, valor_mercadoria
        )
        custo_balsa += custo_balsa_retorno

    # Custo de manutenção (R$/km do veículo, sobre toda distância que a
    # frota própria realmente roda — ida com carga + coleta no cliente
    # (quando não é terceirizada) + volta vazia — já que o desgaste do
    # veículo acontece em qualquer trecho rodado por ele. Coleta
    # terceirizada não conta: quem rodou aquele trecho foi a
    # transportadora contratada, não o veículo da frota própria) e custo
    # do retorno vazio (R$/km, só sobre a distância entre o destino e a
    # filial mais próxima) — custos operacionais do veículo, não do frete
    # em si, então não entram nos multiplicadores de
    # categoria/transporte/SLA. Quando o retorno cruza um corredor de
    # balsa cadastrado (detalhe_balsa_retorno acima), não roda esse
    # trecho de estrada — só a taxa de balsa é cobrada, mesma lógica da
    # ida (ver distancia_faturavel).
    distancia_coleta_propria = 0 if coleta_terceirizada else distancia_coleta
    distancia_retorno_faturavel = 0.0 if detalhe_balsa_retorno else distancia_retorno
    custo_manutencao = v.tarifa_km_manutencao * (
        distancia_faturavel + distancia_coleta_propria + distancia_retorno_faturavel
    )
    custo_retorno = v.tarifa_km_retorno * distancia_retorno_faturavel

    custo_coleta = 0.0
    coleta_fixa_aplicada = False
    coleta_fixa_outro_veiculo = []
    if coleta_terceirizada:
        custo_coleta = valor_coleta_terceirizada
    elif distancia_coleta > 0 or cidade_coleta:
        cidade_normalizada = _cidade_da_retirada(cidade_coleta) if cidade_coleta else None
        # O preço fixo de coleta agora é por rota (filial de onde o
        # veículo sai -> cidade do cliente onde ele coleta) + veículo,
        # não só pela cidade do cliente. Na retirada no cliente,
        # cidade_origem já chega aqui como o nome da filial mais próxima
        # (ver main.py/index.html), e o veículo já foi escolhido pelo
        # peso alguns passos acima.
        cidade_fixa = (
            p.buscar_coleta_cidade_fixa(cidade_origem, cidade_normalizada, v.nome)
            if cidade_normalizada and cidade_origem else None
        )
        if cidade_fixa:
            custo_coleta = cidade_fixa.valor_fixo
            coleta_fixa_aplicada = True
        else:
            if cidade_normalizada and cidade_origem:
                # Cidade+filial bateram, só não pro veículo deste orçamento
                # — avisa em vez de cair calado pra faixa por km.
                coleta_fixa_outro_veiculo = p.buscar_coleta_cidade_fixa_outros_veiculos(
                    cidade_origem, cidade_normalizada, v.nome
                )
            if distancia_coleta > 0:
                faixa_coleta = p.buscar_faixa_coleta(distancia_coleta)
                custo_coleta = faixa_coleta.taxa_fixa + distancia_coleta * faixa_coleta.tarifa_km

    custo_entrega_terceirizada = valor_entrega_terceirizada if entrega_terceirizada else 0.0

    custo_diaria_veiculo, detalhe_diaria_veiculo = _diaria_veiculo_aplicada(
        p, cidade_coleta, cidade_destino, distancia_coleta, coleta_terceirizada, entrega_terceirizada
    )

    # Pedágio calculado por último entre os custos: quando cai no fallback
    # de estimativa (sem praça cadastrada), a % incide sobre frete + todos
    # os custos operacionais + taxas já apurados acima (ver
    # _pedagio_aplicado) -- por isso precisa vir depois deles.
    base_sem_pedagio = (
        frete_ajustado + custo_coleta + custo_entrega_terceirizada + custo_extra_total
        + custo_manutencao + custo_retorno + custo_balsa + custo_diaria_veiculo
        + custo_taxas_adicionais + custo_taxas_regionais
    )
    pedagio, pedagio_estimado_pct, pedagio_pracas = _pedagio_aplicado(
        p, cidade_origem, cidade_destino, v.numero_eixos, base_sem_pedagio, pedagio
    )

    # Separa o frete_total (pré-impostos e pré-margem) em dois grupos pra
    # exibição: custo da operação (transporte em si — frete ajustado,
    # coleta, entrega, pedágio, manutenção, retorno, custos extras, a
    # taxa de balsa e a diária de carreta/cavalo, que são custo de
    # transporte de verdade — a travessia e a parada do veículo são parte
    # do trajeto, não um tributo) e impostos e taxas (taxas adicionais/
    # regionais, cadastradas como "taxa" mas que incidem sobre o valor da
    # mercadoria, não sobre o transporte em si). PIS/COFINS, ICMS e a
    # margem de lucro ficam de fora daqui: são aplicados em cascata por
    # cima desse total, ver mais abaixo.
    total_custo_operacao = (
        frete_ajustado + custo_coleta + custo_entrega_terceirizada
        + custo_extra_total + pedagio + custo_manutencao + custo_retorno + custo_balsa
        + custo_diaria_veiculo
    )
    total_impostos_taxas = custo_taxas_adicionais + custo_taxas_regionais

    frete_total = (
        frete_ajustado
        + custo_coleta
        + custo_entrega_terceirizada
        + custo_taxas_adicionais
        + custo_taxas_regionais
        + custo_balsa
        + custo_diaria_veiculo
        + custo_extra_total
        + pedagio
        + custo_manutencao
        + custo_retorno
    )

    # PIS/COFINS: % simples sobre o frete_total apurado até aqui. A
    # margem de lucro entra em seguida — seu VALOR (R$) é calculado só
    # sobre total_custo_operacao (não sobre impostos/taxas/PIS-COFINS),
    # somado ao frete_total corrente (ver _aplicar_margem_lucro). O ICMS
    # é o último imposto, gross-up "por dentro" sobre o frete total JÁ
    # COM a margem embutida — a alíquota incide sobre o valor total
    # cobrado do cliente, que já inclui o próprio ICMS (ver
    # _aplicar_icms).
    frete_total, frete_sem_pis_cofins, valor_pis_cofins, aliquota_pis_cofins_pct = _aplicar_pis_cofins(p, frete_total)
    frete_total, frete_sem_margem_lucro, valor_margem_lucro = _aplicar_margem_lucro(
        frete_total, total_custo_operacao, MARGEM_LUCRO_PADRAO
    )
    frete_total, frete_sem_icms, valor_icms, icms_aplicavel, aliquota_icms_pct = _aplicar_icms(
        p, frete_total, cidade_origem, cidade_destino
    )
    frete_total, total_impostos_taxas, ajuste_piso_markup = _aplicar_piso_markup(
        frete_total, total_impostos_taxas, total_custo_operacao + total_impostos_taxas
    )

    return {
        "entrada": {
            "peso_kg": peso,
            "paletes": paletes,
            "distancia_km": round(distancia),
            # Nome da filial de escala obrigatória usada pra calcular a
            # distância acima (ver geo_service.calcular_distancia +
            # frete_service.prioridade_rota_aplicavel) — também usada pra
            # achar a distância com travessia de balsa dentro dessa
            # distância total (ver distancia_balsa_km abaixo).
            "rota_obrigatoria": prioridade_rota or None,
            "distancia_coleta_km": round(distancia_coleta),
            "valor_mercadoria": round(valor_mercadoria, 2),
            "veiculo": v.nome,
            "categoria": cat.nome,
            "transporte": transp.nome,
            "sla": s.nome,
        },
        "calculos_intermediarios": {
            "fator_cubagem": transp.fator_cubagem,
            "peso_cubado_kg": round(peso_cubado, 3),
            "peso_considerado_kg": round(peso_considerado, 3),
            "volume_total_m3": round(volume_total_m3, 4),
            "capacidade_util_m3_veiculo": v.capacidade_m3,
            "percentual_capacidade_util_veiculo": v.percentual_capacidade_util,
            "capacidade_disponivel_m3_veiculo": (
                round(v.capacidade_m3 * (v.percentual_capacidade_util / 100), 4) if v.capacidade_m3 > 0 else None
            ),
            "capacidade_ocupada_pct": (
                round(volume_total_m3 / (v.capacidade_m3 * (v.percentual_capacidade_util / 100)) * 100, 1)
                if v.capacidade_m3 > 0 else None
            ),
            "distancia_balsa_km": round(balsa_km),
            "distancia_faturavel_km": round(distancia_faturavel),
            "tarifa_km_veiculo": tarifa_km_usada,
            "faixa_km_aplicada": faixa_km_aplicada,
            "custo_km": round(custo_km, 2),
            "peso_excedente_kg": round(peso_excedente, 3),
            "valor_tonelada_excedente": v.valor_tonelada_excedente,
            "custo_peso_excedente": round(custo_peso_excedente, 2),
            "custo_tabela_lotacao_destino": (
                round(custo_tabela_lotacao_destino, 2) if custo_tabela_lotacao_destino is not None else None
            ),
            "frete_base": round(frete_base, 2),
            "multiplicador_categoria": cat.multiplicador,
            "multiplicador_transporte": transp.multiplicador,
            "multiplicador_sla": s.multiplicador,
            "frete_ajustado": round(frete_ajustado, 2),
            "custo_coleta": round(custo_coleta, 2),
            "coleta_fixa_por_cidade": coleta_fixa_aplicada,
            "coleta_fixa_outro_veiculo": coleta_fixa_outro_veiculo or None,
            "coleta_terceirizada": coleta_terceirizada,
            "transportadora_coleta_nome": transportadora_coleta_nome if coleta_terceirizada else None,
            "custo_entrega_terceirizada": round(custo_entrega_terceirizada, 2),
            "entrega_terceirizada": entrega_terceirizada,
            "transportadora_entrega_nome": transportadora_entrega_nome if entrega_terceirizada else None,
            "pedagio": round(pedagio, 2),
            "pedagio_estimado_pct": PEDAGIO_PCT_FALLBACK if pedagio_estimado_pct else None,
            "pedagio_pracas": pedagio_pracas,
            "distancia_manutencao_km": round(
                distancia_faturavel + distancia_coleta_propria + distancia_retorno_faturavel
            ),
            "custo_manutencao": round(custo_manutencao, 2),
            "tarifa_km_manutencao": v.tarifa_km_manutencao,
            "custo_retorno": round(custo_retorno, 2),
            "tarifa_km_retorno": v.tarifa_km_retorno,
            "distancia_retorno_km": round(distancia_retorno),
            "custos_extras": detalhe_custos_extras or None,
            "custo_extra_total": round(custo_extra_total, 2),
            "taxas_adicionais": detalhe_taxas,
            "custo_taxas_adicionais": round(custo_taxas_adicionais, 2),
            "taxas_regionais": detalhe_taxas_regionais,
            "custo_taxas_regionais": round(custo_taxas_regionais, 2),
            "taxa_balsa": detalhe_balsa,
            "taxa_balsa_retorno": detalhe_balsa_retorno,
            "custo_balsa": round(custo_balsa, 2),
            "balsa_outro_veiculo": balsa_outro_veiculo or None,
            "diaria_veiculo": detalhe_diaria_veiculo,
            "custo_diaria_veiculo": round(custo_diaria_veiculo, 2),
            "total_custo_operacao": round(total_custo_operacao, 2),
            "total_impostos_taxas": round(total_impostos_taxas, 2),
            "ajuste_piso_markup": round(ajuste_piso_markup, 2),
            "margem_lucro_pct": MARGEM_LUCRO_PADRAO,
            "frete_sem_margem_lucro": round(frete_sem_margem_lucro, 2),
            "valor_margem_lucro": round(valor_margem_lucro, 2),
            "aliquota_pis_cofins_pct": aliquota_pis_cofins_pct,
            "frete_sem_pis_cofins": round(frete_sem_pis_cofins, 2),
            "valor_pis_cofins": round(valor_pis_cofins, 2),
            "uf_origem_icms": icms_aplicavel and _uf_de_origem_ou_destino(p, cidade_origem) or None,
            "uf_destino_icms": icms_aplicavel and _uf_de_origem_ou_destino(p, cidade_destino) or None,
            "aliquota_icms_pct": aliquota_icms_pct,
            "frete_sem_icms": round(frete_sem_icms, 2),
            "valor_icms": round(valor_icms, 2),
        },
        "resultado": {
            "frete_total": round(frete_total, 2),
            "prazo_estimado_dias_uteis": _prazo_estimado_dias_uteis(distancia_faturavel, balsa_km),
        },
    }


def calcular_orcamento_fracionado(
    peso: float,
    paletes: list[dict],
    distancia: float,
    valor_mercadoria: float,
    categoria: str,
    transporte: str,
    sla: str,
    veiculo: str,
    cidade_origem: str | None = None,
    cidade_destino: str | None = None,
    pedagio: float = 0,
    prioridade_rota: str | None = None,
    custos_extras: list[dict] | None = None,
    gris_pct: float | None = None,
    ad_valorem_pct: float | None = None,
) -> dict:
    """Frete Fracionado -- mesma logica de calcular_orcamento pra tudo que
    nao eh o frete base (categoria/transporte/SLA, taxas adicionais e
    regionais, taxa de balsa, ICMS, PIS/COFINS, margem de lucro), mas o
    frete base vem de faixas de peso + distancia (Tabela de Precos ->
    Fracionado, tipo_frete='Fracionado' em faixas_peso/faixas_distancia)
    em vez de veiculo escolhido automaticamente pelo peso:

        faixa_peso = faixa cujo "de" cobre o peso considerado
        custo_peso = faixa_peso.tarifa_base + faixa_peso.custo_kg_adicional * (peso_considerado - faixa_peso.de)
        faixa_distancia = faixa cujo "de" cobre a distancia faturavel
        custo_distancia = faixa_distancia.taxa_fixa + faixa_distancia.tarifa_km * distancia_faturavel
        frete_base = custo_peso + custo_distancia

    `veiculo` aqui eh so uma referencia (ver /parametros/veiculos) pra achar
    pedagio (numero de eixos), taxa de balsa e coleta fixa cadastrados por
    veiculo -- nao define nenhuma tarifa do frete base.

    Essa primeira versao cobre so transferencia entre filiais: sem coleta/
    entrega no endereco do cliente (CEP), sem transportadora terceirizada e
    sem retorno vazio de veiculo -- conceitos de veiculo dedicado que nao
    se aplicam a uma carga fracionada compartilhada com outros clientes.
    Pela mesma razao, tambem nao ha manutencao de veiculo nem peso
    excedente: o desgaste do veiculo eh custo de quem presta o frete
    fracionado como servico contratado, e o peso ja escala continuamente
    pelo custo_kg_adicional da faixa, sem o conceito de "veiculo cheio"."""
    if peso <= 0:
        raise FreteInputError("Peso deve ser maior que zero.")
    if not paletes:
        raise FreteInputError("Informe ao menos um palete com comprimento, largura e altura.")
    for palete in paletes:
        if palete["comprimento"] <= 0 or palete["largura"] <= 0 or palete["altura"] <= 0:
            raise FreteInputError("Comprimento, largura e altura de cada palete devem ser maiores que zero.")
        if palete.get("quantidade", 1) < 1:
            raise FreteInputError("A quantidade de cada palete deve ser pelo menos 1.")
    if distancia <= 0:
        raise FreteInputError("Distância deve ser maior que zero.")
    if valor_mercadoria < 0:
        raise FreteInputError("Valor da mercadoria não pode ser negativo.")
    if pedagio < 0:
        raise FreteInputError("Valor de pedágio não pode ser negativo.")
    if gris_pct is not None:
        if _taxa_customizavel_e_tipo_fixo(parametros, _NOME_TAXA_GRIS):
            raise FreteInputError(
                "GRIS está cadastrado como valor fixo em Tabela de Preços — não é possível substituir por "
                "um % digitado nesse orçamento."
            )
        piso_gris = _piso_taxa_customizavel(parametros, _NOME_TAXA_GRIS)
        if gris_pct < piso_gris:
            raise FreteInputError(f"GRIS ({gris_pct}%) abaixo do mínimo cadastrado ({piso_gris}%).")
    if ad_valorem_pct is not None:
        if _taxa_customizavel_e_tipo_fixo(parametros, _NOME_TAXA_AD_VALOREM):
            raise FreteInputError(
                "Ad Valorem está cadastrado como valor fixo em Tabela de Preços — não é possível substituir "
                "por um % digitado nesse orçamento."
            )
        piso_ad_valorem = _piso_taxa_customizavel(parametros, _NOME_TAXA_AD_VALOREM)
        if ad_valorem_pct < piso_ad_valorem:
            raise FreteInputError(f"Ad Valorem ({ad_valorem_pct}%) abaixo do mínimo cadastrado ({piso_ad_valorem}%).")
    custos_extras = custos_extras or []
    for custo_extra in custos_extras:
        if custo_extra.get("categoria") not in CATEGORIAS_CUSTO_EXTRA:
            opcoes = ", ".join(CATEGORIAS_CUSTO_EXTRA)
            raise FreteInputError(
                f"Categoria de custo extra '{custo_extra.get('categoria')}' inválida. Opções: {opcoes}"
            )
        if custo_extra.get("valor", 0) < 0:
            raise FreteInputError("Valor de custo extra não pode ser negativo.")

    p = parametros
    transp = p.buscar_transporte(transporte)
    cat = p.buscar_categoria(categoria)
    s = p.buscar_sla(sla)
    v = p.buscar_veiculo(veiculo)

    volume_total_m3, peso_cubado, peso_considerado = _calcular_cubagem(peso, paletes, transp)

    # Mesma regra de calcular_orcamento: km de balsa nao entra na tarifa
    # (nem de peso, nem de distancia) por cima da taxa de balsa fixa ja
    # cobrada abaixo, senao a travessia seria cobrada duas vezes.
    balsa_km = distancia_balsa_km(p, cidade_origem, cidade_destino, prioridade_rota)
    distancia_faturavel = max(distancia - balsa_km, 0.0)

    # Rota com custo pré-tabelado por faixa de peso (ver
    # _custo_fracionado_destino_aplicavel) substitui as faixas genéricas de
    # peso/distância inteiramente -- mesma lógica de
    # _custo_lotacao_destino_aplicavel em calcular_orcamento: o valor já é
    # o custo operacional completo (coleta+embarque+entrega somados por
    # faixa de peso, da planilha legada), então categoria/transporte/sla
    # NÃO se aplicam aqui pela mesma razão. Sem rota cadastrada pra essa
    # origem/destino, cai no fallback de faixas_peso_fracionado/
    # faixas_distancia_fracionado genérico (comportamento histórico).
    faixa_peso = faixa_distancia = None
    custo_base_peso = custo_base_distancia = None
    custo_tabela_fracionado_destino = _custo_fracionado_destino_aplicavel(
        p, cidade_origem, cidade_destino, peso_considerado
    )
    if custo_tabela_fracionado_destino is not None:
        frete_base = custo_tabela_fracionado_destino
        frete_ajustado = frete_base
    else:
        faixa_peso = p.buscar_faixa_peso_fracionado(peso_considerado)
        custo_base_peso = faixa_peso.tarifa_base + faixa_peso.custo_kg_adicional * max(peso_considerado - faixa_peso.de, 0)

        faixa_distancia = p.buscar_faixa_distancia_fracionado(distancia_faturavel)
        custo_base_distancia = faixa_distancia.taxa_fixa + faixa_distancia.tarifa_km * distancia_faturavel

        frete_base = custo_base_peso + custo_base_distancia
        frete_ajustado = frete_base * cat.multiplicador * transp.multiplicador * s.multiplicador

    detalhe_custos_extras, custo_extra_total = _custos_extras_aplicados(custos_extras)
    detalhe_taxas, custo_taxas_adicionais = _taxas_adicionais_aplicadas(p, valor_mercadoria, gris_pct, ad_valorem_pct)
    detalhe_taxas_regionais, custo_taxas_regionais = _taxas_regionais_aplicadas(
        p, cidade_origem, cidade_destino, valor_mercadoria
    )
    custo_balsa, detalhe_balsa, balsa_outro_veiculo = _taxa_balsa_aplicada(
        p, cidade_origem, cidade_destino, v.nome, valor_mercadoria
    )

    # Pedágio calculado depois dos demais custos: no fallback de
    # estimativa (sem praça cadastrada), a % incide sobre frete + custos
    # operacionais + taxas já apurados acima (ver _pedagio_aplicado).
    base_sem_pedagio = frete_ajustado + custo_extra_total + custo_balsa + custo_taxas_adicionais + custo_taxas_regionais
    pedagio, pedagio_estimado_pct, pedagio_pracas = _pedagio_aplicado(
        p, cidade_origem, cidade_destino, v.numero_eixos, base_sem_pedagio, pedagio
    )

    # Mesma separação de calcular_orcamento: custo da operação (frete
    # ajustado, pedágio, custos extras e a taxa de balsa, custo de
    # transporte de verdade) x impostos e taxas (taxas adicionais/
    # regionais, que incidem sobre o valor da mercadoria) -- PIS/COFINS,
    # ICMS e margem de lucro ficam de fora (aplicados em cascata por cima,
    # margem por último, ver abaixo).
    total_custo_operacao = frete_ajustado + custo_extra_total + pedagio + custo_balsa
    total_impostos_taxas = custo_taxas_adicionais + custo_taxas_regionais

    frete_total = (
        frete_ajustado
        + custo_taxas_adicionais
        + custo_taxas_regionais
        + custo_balsa
        + custo_extra_total
        + pedagio
    )

    # Mesma ordem de calcular_orcamento: PIS/COFINS (% simples) sobre o
    # custo da operação + impostos e taxas, a margem de lucro em seguida
    # (valor calculado só sobre total_custo_operacao), e o ICMS por
    # último — gross-up "por dentro" sobre o frete total já com a margem
    # embutida (ver _aplicar_pis_cofins/_aplicar_margem_lucro/_aplicar_icms).
    frete_total, frete_sem_pis_cofins, valor_pis_cofins, aliquota_pis_cofins_pct = _aplicar_pis_cofins(p, frete_total)
    frete_total, frete_sem_margem_lucro, valor_margem_lucro = _aplicar_margem_lucro(
        frete_total, total_custo_operacao, MARGEM_LUCRO_PADRAO
    )
    frete_total, frete_sem_icms, valor_icms, icms_aplicavel, aliquota_icms_pct = _aplicar_icms(
        p, frete_total, cidade_origem, cidade_destino
    )
    frete_total, total_impostos_taxas, ajuste_piso_markup = _aplicar_piso_markup(
        frete_total, total_impostos_taxas, total_custo_operacao + total_impostos_taxas
    )

    return {
        "entrada": {
            "peso_kg": peso,
            "paletes": paletes,
            "distancia_km": round(distancia),
            "rota_obrigatoria": prioridade_rota or None,
            "valor_mercadoria": round(valor_mercadoria, 2),
            "veiculo": v.nome,
            "categoria": cat.nome,
            "transporte": transp.nome,
            "sla": s.nome,
            "tipo_frete": "Fracionado",
        },
        "calculos_intermediarios": {
            "fator_cubagem": transp.fator_cubagem,
            "peso_cubado_kg": round(peso_cubado, 3),
            "peso_considerado_kg": round(peso_considerado, 3),
            "volume_total_m3": round(volume_total_m3, 4),
            "distancia_balsa_km": round(balsa_km),
            "distancia_faturavel_km": round(distancia_faturavel),
            "custo_tabela_fracionado_destino": (
                round(custo_tabela_fracionado_destino, 2) if custo_tabela_fracionado_destino is not None else None
            ),
            "faixa_peso_de": faixa_peso.de if faixa_peso else None,
            "faixa_peso_ate": faixa_peso.ate if faixa_peso else None,
            "tarifa_base_peso": faixa_peso.tarifa_base if faixa_peso else None,
            "custo_kg_adicional_peso": faixa_peso.custo_kg_adicional if faixa_peso else None,
            "custo_base_peso": round(custo_base_peso, 2) if custo_base_peso is not None else None,
            "faixa_distancia_de": faixa_distancia.de if faixa_distancia else None,
            "faixa_distancia_ate": faixa_distancia.ate if faixa_distancia else None,
            "taxa_fixa_distancia": faixa_distancia.taxa_fixa if faixa_distancia else None,
            "tarifa_km_distancia": faixa_distancia.tarifa_km if faixa_distancia else None,
            "custo_base_distancia": round(custo_base_distancia, 2) if custo_base_distancia is not None else None,
            "frete_base": round(frete_base, 2),
            "multiplicador_categoria": cat.multiplicador,
            "multiplicador_transporte": transp.multiplicador,
            "multiplicador_sla": s.multiplicador,
            "frete_ajustado": round(frete_ajustado, 2),
            "pedagio": round(pedagio, 2),
            "pedagio_estimado_pct": PEDAGIO_PCT_FALLBACK if pedagio_estimado_pct else None,
            "pedagio_pracas": pedagio_pracas,
            "custos_extras": detalhe_custos_extras or None,
            "custo_extra_total": round(custo_extra_total, 2),
            "taxas_adicionais": detalhe_taxas,
            "custo_taxas_adicionais": round(custo_taxas_adicionais, 2),
            "taxas_regionais": detalhe_taxas_regionais,
            "custo_taxas_regionais": round(custo_taxas_regionais, 2),
            "taxa_balsa": detalhe_balsa,
            "custo_balsa": round(custo_balsa, 2),
            "balsa_outro_veiculo": balsa_outro_veiculo or None,
            "total_custo_operacao": round(total_custo_operacao, 2),
            "total_impostos_taxas": round(total_impostos_taxas, 2),
            "ajuste_piso_markup": round(ajuste_piso_markup, 2),
            "margem_lucro_pct": MARGEM_LUCRO_PADRAO,
            "frete_sem_margem_lucro": round(frete_sem_margem_lucro, 2),
            "valor_margem_lucro": round(valor_margem_lucro, 2),
            "aliquota_pis_cofins_pct": aliquota_pis_cofins_pct,
            "frete_sem_pis_cofins": round(frete_sem_pis_cofins, 2),
            "valor_pis_cofins": round(valor_pis_cofins, 2),
            "uf_origem_icms": icms_aplicavel and _uf_de_origem_ou_destino(p, cidade_origem) or None,
            "uf_destino_icms": icms_aplicavel and _uf_de_origem_ou_destino(p, cidade_destino) or None,
            "aliquota_icms_pct": aliquota_icms_pct,
            "frete_sem_icms": round(frete_sem_icms, 2),
            "valor_icms": round(valor_icms, 2),
        },
        "resultado": {
            "frete_total": round(frete_total, 2),
            "prazo_estimado_dias_uteis": (
                _prazo_fracionado_destino_aplicavel(p, cidade_origem, cidade_destino)
                or _prazo_estimado_dias_uteis(distancia_faturavel, balsa_km)
            ),
        },
    }