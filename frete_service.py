"""
Lógica de cálculo de frete. Os parâmetros (veículos, taxas adicionais,
coleta por cidade, categorias, transportes, SLAs, filiais) são lidos do
banco SQLite (frete.db) a cada recarga — edite pela tela "Tabela de
Preços" ou direto no banco com o DB Browser for SQLite, e chame POST
/admin/reload para aplicar (a tela já faz isso sozinha a cada edição).

Fórmula do frete principal (por veículo):
    custo_km = veiculo.tarifa_km * distancia
    peso_excedente = max(peso_considerado - veiculo.peso_incluso_kg, 0)
    custo_peso_excedente = peso_excedente * veiculo.valor_kg_excedente
    frete_base = custo_km + custo_peso_excedente
    frete_ajustado = frete_base * categoria.multiplicador * transporte.multiplicador * sla.multiplicador

Em cima disso somam-se: taxas adicionais (fixas em R$ ou % do valor da
mercadoria) e a taxa de coleta (quando há retirada no cliente — usa
preço fixo se a rota cidade do cliente -> filial + veículo estiver
cadastrada, senão cai na faixa por km).

As tabelas antigas de "tipo de frete" (faixas_peso/faixas_distancia)
continuam existindo no banco por compatibilidade, mas não são mais
usadas no cálculo — o veículo assumiu esse papel.
"""

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


@dataclass
class Veiculo:
    nome: str
    de: float
    ate: float
    tarifa_km: float
    peso_incluso_kg: float
    valor_kg_excedente: float
    tarifa_km_retorno: float = 0
    tarifa_km_manutencao: float = 0
    capacidade_m3: float = 0


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


class ParametrosFrete:
    """Mantém em memória os parâmetros lidos do banco."""

    def __init__(self):
        self.veiculos: dict[str, Veiculo] = {}
        self.veiculos_por_peso: list[Veiculo] = []
        self.taxas_adicionais: list[TaxaAdicional] = []
        self.taxas_regionais: list[TaxaRegional] = []
        self.faixas_coleta: list[FaixaDistancia] = []
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
                    r["nome"], r["de"], r["ate"], r["tarifa_km"], r["peso_incluso_kg"], r["valor_kg_excedente"],
                    r["tarifa_km_retorno"], r["tarifa_km_manutencao"], r["capacidade_m3"],
                )
                for r in conn.execute("SELECT * FROM veiculos")
            }
            self.veiculos_por_peso = sorted(self.veiculos.values(), key=lambda v: v.de)
            self.taxas_adicionais = [
                TaxaAdicional(r["nome"], r["tipo"], r["valor"])
                for r in conn.execute("SELECT * FROM taxas_adicionais")
            ]
            self.taxas_regionais = [
                TaxaRegional(r["cidade"], r["nome"], r["tipo"], r["valor"])
                for r in conn.execute("SELECT * FROM taxas_regionais")
            ]
            self.faixas_coleta = sorted(
                (FaixaDistancia(r["de"], r["ate"], r["taxa_fixa"], r["tarifa_km"])
                 for r in conn.execute("SELECT * FROM faixas_coleta")),
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
                r["nome"].strip().lower(): Filial(r["nome"], r["endereco"], r["latitude"], r["longitude"])
                for r in conn.execute("SELECT * FROM filiais")
            }

        if not self.veiculos:
            raise FreteConfigError("Nenhum veículo cadastrado (tabela veiculos).")
        if not self.faixas_coleta:
            raise FreteConfigError("Nenhuma faixa de coleta cadastrada (tabela faixas_coleta).")
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
        Se a carga não couber em 80% da capacidade útil (m³) desse veículo,
        sobe para o próximo veículo maior (por peso) que tenha espaço —
        um veículo sem capacidade_m3 cadastrada (0) é tratado como sem
        limite de volume, pra não quebrar quem ainda não configurou isso."""
        escolhido = self.buscar_veiculo_por_peso(peso_considerado)
        if volume_total_m3 <= 0:
            return escolhido

        def cabe(v: Veiculo) -> bool:
            return v.capacidade_m3 <= 0 or volume_total_m3 <= v.capacidade_m3 * 0.8

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
            f"Volume da carga ({volume_total_m3:.3f} m³) ultrapassa 80% da capacidade útil de todos os "
            f"veículos disponíveis a partir de '{escolhido.nome}'. Cadastre um veículo maior na Tabela de "
            f"Preços ou revise as dimensões dos paletes informados."
        )

    def buscar_faixa_coleta(self, distancia: float) -> FaixaDistancia:
        candidatas = [f for f in self.faixas_coleta if f.de <= distancia]
        if not candidatas:
            raise FreteInputError(f"Distância de coleta {distancia}km abaixo da menor faixa configurada.")
        return candidatas[-1]

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
    cidade de origem OU de destino do frete (comparação case-insensitive)."""
    cidades_da_rota = set()
    for texto in (cidade_origem, cidade_destino):
        cidade = _cidade_da_retirada(texto) if texto else None
        if cidade:
            cidades_da_rota.add(cidade.strip().lower())
    if not cidades_da_rota:
        return []
    return [t for t in p.taxas_regionais if t.cidade.strip().lower() in cidades_da_rota]


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
) -> dict:
    if peso <= 0:
        raise FreteInputError("Peso deve ser maior que zero.")
    if not paletes:
        raise FreteInputError("Informe ao menos um palete com comprimento, largura e altura.")
    for palete in paletes:
        if palete["comprimento"] <= 0 or palete["largura"] <= 0 or palete["altura"] <= 0:
            raise FreteInputError("Comprimento, largura e altura de cada palete devem ser maiores que zero.")
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

    p = parametros
    transp = p.buscar_transporte(transporte)
    cat = p.buscar_categoria(categoria)
    s = p.buscar_sla(sla)

    volume_total_cm3 = sum(pal["comprimento"] * pal["largura"] * pal["altura"] for pal in paletes)
    volume_total_m3 = volume_total_cm3 / 1_000_000
    peso_cubado = volume_total_cm3 / transp.fator_cubagem
    peso_considerado = max(peso, peso_cubado)

    v = p.buscar_veiculo_por_peso_e_volume(peso_considerado, volume_total_m3)

    custo_km = v.tarifa_km * distancia
    peso_excedente = max(peso_considerado - v.peso_incluso_kg, 0)
    custo_peso_excedente = peso_excedente * v.valor_kg_excedente

    frete_base = custo_km + custo_peso_excedente
    frete_ajustado = frete_base * cat.multiplicador * transp.multiplicador * s.multiplicador

    # Custo de manutenção (R$/km do veículo, sobre a distância de ida com
    # carga) e custo do retorno vazio (R$/km, sobre a distância entre o
    # destino e a filial mais próxima) — custos operacionais do veículo,
    # não do frete em si, então não entram nos multiplicadores de
    # categoria/transporte/SLA.
    custo_manutencao = v.tarifa_km_manutencao * distancia
    custo_retorno = v.tarifa_km_retorno * distancia_retorno

    # Taxas adicionais (fixas em R$ ou % do valor da mercadoria)
    detalhe_taxas = []
    custo_taxas_adicionais = 0.0
    for taxa in p.taxas_adicionais:
        if taxa.tipo == "percentual":
            valor_taxa = valor_mercadoria * (taxa.valor / 100)
        else:
            valor_taxa = taxa.valor
        custo_taxas_adicionais += valor_taxa
        detalhe_taxas.append({
            "nome": taxa.nome, "tipo": taxa.tipo,
            "valor_configurado": taxa.valor, "valor_aplicado": round(valor_taxa, 2),
        })

    # Taxas regionais — só entram se a cidade de origem ou de destino do
    # frete bater com alguma cidade cadastrada (ex: taxa de zona franca
    # em Manaus, taxa de área de risco em determinada cidade etc.)
    detalhe_taxas_regionais = []
    custo_taxas_regionais = 0.0
    for taxa in _taxas_regionais_aplicaveis(p, cidade_origem, cidade_destino):
        if taxa.tipo == "percentual":
            valor_taxa = valor_mercadoria * (taxa.valor / 100)
        else:
            valor_taxa = taxa.valor
        custo_taxas_regionais += valor_taxa
        detalhe_taxas_regionais.append({
            "nome": taxa.nome, "cidade": taxa.cidade, "tipo": taxa.tipo,
            "valor_configurado": taxa.valor, "valor_aplicado": round(valor_taxa, 2),
        })

    custo_coleta = 0.0
    coleta_fixa_aplicada = False
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
            db.buscar_coleta_cidade_fixa(cidade_origem, cidade_normalizada, v.nome)
            if cidade_normalizada and cidade_origem else None
        )
        if cidade_fixa:
            custo_coleta = cidade_fixa["valor_fixo"]
            coleta_fixa_aplicada = True
        elif distancia_coleta > 0:
            faixa_coleta = p.buscar_faixa_coleta(distancia_coleta)
            custo_coleta = faixa_coleta.taxa_fixa + distancia_coleta * faixa_coleta.tarifa_km

    custo_entrega_terceirizada = valor_entrega_terceirizada if entrega_terceirizada else 0.0

    frete_total = (
        frete_ajustado
        + custo_coleta
        + custo_entrega_terceirizada
        + custo_taxas_adicionais
        + custo_taxas_regionais
        + pedagio
        + custo_manutencao
        + custo_retorno
    )

    return {
        "entrada": {
            "peso_kg": peso,
            "paletes": paletes,
            "distancia_km": round(distancia),
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
            "capacidade_disponivel_m3_veiculo": round(v.capacidade_m3 * 0.8, 4) if v.capacidade_m3 > 0 else None,
            "capacidade_ocupada_pct": (
                round(volume_total_m3 / (v.capacidade_m3 * 0.8) * 100, 1) if v.capacidade_m3 > 0 else None
            ),
            "tarifa_km_veiculo": v.tarifa_km,
            "custo_km": round(custo_km, 2),
            "peso_incluso_veiculo_kg": v.peso_incluso_kg,
            "peso_excedente_kg": round(peso_excedente, 3),
            "valor_kg_excedente": v.valor_kg_excedente,
            "custo_peso_excedente": round(custo_peso_excedente, 2),
            "frete_base": round(frete_base, 2),
            "multiplicador_categoria": cat.multiplicador,
            "multiplicador_transporte": transp.multiplicador,
            "multiplicador_sla": s.multiplicador,
            "frete_ajustado": round(frete_ajustado, 2),
            "custo_coleta": round(custo_coleta, 2),
            "coleta_fixa_por_cidade": coleta_fixa_aplicada,
            "coleta_terceirizada": coleta_terceirizada,
            "transportadora_coleta_nome": transportadora_coleta_nome if coleta_terceirizada else None,
            "custo_entrega_terceirizada": round(custo_entrega_terceirizada, 2),
            "entrega_terceirizada": entrega_terceirizada,
            "transportadora_entrega_nome": transportadora_entrega_nome if entrega_terceirizada else None,
            "pedagio": round(pedagio, 2),
            "custo_manutencao": round(custo_manutencao, 2),
            "tarifa_km_manutencao": v.tarifa_km_manutencao,
            "custo_retorno": round(custo_retorno, 2),
            "tarifa_km_retorno": v.tarifa_km_retorno,
            "distancia_retorno_km": round(distancia_retorno),
            "taxas_adicionais": detalhe_taxas,
            "custo_taxas_adicionais": round(custo_taxas_adicionais, 2),
            "taxas_regionais": detalhe_taxas_regionais,
            "custo_taxas_regionais": round(custo_taxas_regionais, 2),
        },
        "resultado": {
            "frete_total": round(frete_total, 2),
            "prazo_estimado_dias_uteis": s.prazo_dias,
        },
    }