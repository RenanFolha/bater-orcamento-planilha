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


def _valor_taxa(tipo: str, valor: float, valor_mercadoria: float) -> float:
    """Aplica uma taxa (adicional, regional ou de balsa) conforme seu tipo
    cadastrado: 'percentual' incide sobre o valor da mercadoria, 'fixo' é o
    próprio valor cadastrado em R$."""
    return valor_mercadoria * (valor / 100) if tipo == "percentual" else valor


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


class ParametrosFrete:
    """Mantém em memória os parâmetros lidos do banco."""

    def __init__(self):
        self.veiculos: dict[str, Veiculo] = {}
        self.veiculos_por_peso: list[Veiculo] = []
        self.faixas_km_veiculo: dict[str, list[FaixaKmVeiculo]] = {}
        self.taxas_adicionais: list[TaxaAdicional] = []
        self.taxas_regionais: list[TaxaRegional] = []
        self.taxas_balsa: list[TaxaBalsa] = []
        self.coleta_cidades_fixas: list[ColetaCidadeFixa] = []
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
                    r["nome"], r["de"], r["ate"], r["tarifa_km"], r["valor_tonelada_excedente"],
                    r["tarifa_km_retorno"], r["tarifa_km_manutencao"], r["capacidade_m3"],
                    r["percentual_capacidade_util"],
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
            self.coleta_cidades_fixas = [
                ColetaCidadeFixa(r["filial_origem"], r["cidade_destino"], r["veiculo"], r["valor_fixo"])
                for r in conn.execute("SELECT * FROM coleta_cidades_fixas ORDER BY id")
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


TAXA_BALSA_CORINGA = "*"  # cidade_origem/cidade_destino/veiculo cadastrado como "*" casa com qualquer valor


def _taxa_balsa_bate_campo(cadastrado: str, valor: str) -> bool:
    return cadastrado == TAXA_BALSA_CORINGA or cadastrado == valor


def _normalizar_par_cidades(cidade_origem: str | None, cidade_destino: str | None) -> tuple[str, str] | None:
    """Extrai e normaliza (minúsculas, sem acento) a cidade de origem e
    destino de dois textos de endereço/filial — usado pelas checagens de
    taxa de balsa direcionais. Devolve None se alguma das duas não puder
    ser identificada."""
    if not cidade_origem or not cidade_destino:
        return None
    cid_o = _cidade_da_retirada(cidade_origem)
    cid_d = _cidade_da_retirada(cidade_destino)
    if not cid_o or not cid_d:
        return None
    return db.normalizar_texto(cid_o), db.normalizar_texto(cid_d)


def _taxa_balsa_aplicavel(
    p: "ParametrosFrete", cidade_origem: str | None, cidade_destino: str | None, veiculo: str
) -> TaxaBalsa | None:
    """Retorna a taxa de balsa cadastrada pra essa rota + veículo, se
    houver — direcional (cidade_origem -> cidade_destino nessa ordem
    exata): ida e volta são cotações independentes, então uma taxa
    cadastrada só pra A->B não se aplica automaticamente à rota B->A. O
    valor também pode variar por veículo (balsa cobra por categoria do
    veículo embarcado), então precisa bater o veículo escolhido também.

    Cada um dos três campos (cidade_origem, cidade_destino, veiculo)
    aceita "*" como curinga — ex: uma travessia por corredor fluvial
    (Belém↔Manaus) vale pra praticamente qualquer origem no Brasil, sem
    precisar cadastrar uma linha por UF. Quando mais de uma linha bate
    (ex: um curinga "*"→Manaus e uma exceção específica cadastrada pra
    uma origem que NÃO usa balsa naquele destino), vence a linha mais
    específica — quem tem mais campos exatos (não-curinga)."""
    par = _normalizar_par_cidades(cidade_origem, cidade_destino)
    if par is None:
        return None
    cid_o, cid_d = par
    veic = db.normalizar_texto(veiculo)
    candidatas = []
    for t in p.taxas_balsa:
        t_o, t_d, t_v = db.normalizar_texto(t.cidade_origem), db.normalizar_texto(t.cidade_destino), db.normalizar_texto(t.veiculo)
        if _taxa_balsa_bate_campo(t_o, cid_o) and _taxa_balsa_bate_campo(t_d, cid_d) and _taxa_balsa_bate_campo(t_v, veic):
            especificidade = (t_o != TAXA_BALSA_CORINGA) + (t_d != TAXA_BALSA_CORINGA) + (t_v != TAXA_BALSA_CORINGA)
            candidatas.append((especificidade, t))
    if not candidatas:
        return None
    return max(candidatas, key=lambda par: par[0])[1]


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
    cid_o, cid_d = par
    veic_atual = db.normalizar_texto(veiculo_atual)
    encontrados = {
        t.veiculo for t in p.taxas_balsa
        if _taxa_balsa_bate_campo(db.normalizar_texto(t.cidade_origem), cid_o)
        and _taxa_balsa_bate_campo(db.normalizar_texto(t.cidade_destino), cid_d)
        and db.normalizar_texto(t.veiculo) != veic_atual
    }
    return sorted(encontrados)


@dataclass
class SelecaoVeiculo:
    veiculo: Veiculo
    volume_total_m3: float
    peso_cubado: float
    peso_considerado: float


def escolher_veiculo(peso: float, paletes: list[dict], transp: Transporte) -> SelecaoVeiculo:
    """Mesma lógica de escolha de veículo usada em calcular_orcamento
    (peso real x peso cubado, dentro da capacidade em m³) — extraída pra
    função própria porque geo_service também precisa saber qual veículo
    seria escolhido, antes mesmo de calcular o orçamento (usada pra achar
    uma rota já cotada no histórico com o mesmo veículo, ver
    geo_service._buscar_rota_no_historico)."""
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
    veiculo = parametros.buscar_veiculo_por_peso_e_volume(peso_considerado, volume_total_m3)
    return SelecaoVeiculo(veiculo, volume_total_m3, peso_cubado, peso_considerado)


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

    p = parametros
    transp = p.buscar_transporte(transporte)
    cat = p.buscar_categoria(categoria)
    s = p.buscar_sla(sla)

    selecao = escolher_veiculo(peso, paletes, transp)
    v = selecao.veiculo
    volume_total_m3 = selecao.volume_total_m3
    peso_cubado = selecao.peso_cubado
    peso_considerado = selecao.peso_considerado

    tarifa_km_usada, faixa_km_aplicada = p.tarifa_km_efetiva(v, distancia)
    custo_km = tarifa_km_usada * distancia
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

    frete_base = custo_km + custo_peso_excedente
    frete_ajustado = frete_base * cat.multiplicador * transp.multiplicador * s.multiplicador

    # Custo de manutenção (R$/km do veículo, sobre toda distância que a
    # frota própria realmente roda — ida com carga + coleta no cliente
    # (quando não é terceirizada) + volta vazia — já que o desgaste do
    # veículo acontece em qualquer trecho rodado por ele. Coleta
    # terceirizada não conta: quem rodou aquele trecho foi a
    # transportadora contratada, não o veículo da frota própria) e custo
    # do retorno vazio (R$/km, só sobre a distância entre o destino e a
    # filial mais próxima) — custos operacionais do veículo, não do frete
    # em si, então não entram nos multiplicadores de
    # categoria/transporte/SLA.
    distancia_coleta_propria = 0 if coleta_terceirizada else distancia_coleta
    custo_manutencao = v.tarifa_km_manutencao * (distancia + distancia_coleta_propria + distancia_retorno)
    custo_retorno = v.tarifa_km_retorno * distancia_retorno

    # Taxas adicionais (fixas em R$ ou % do valor da mercadoria)
    detalhe_taxas = []
    custo_taxas_adicionais = 0.0
    for taxa in p.taxas_adicionais:
        valor_taxa = _valor_taxa(taxa.tipo, taxa.valor, valor_mercadoria)
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
        valor_taxa = _valor_taxa(taxa.tipo, taxa.valor, valor_mercadoria)
        custo_taxas_regionais += valor_taxa
        detalhe_taxas_regionais.append({
            "nome": taxa.nome, "cidade": taxa.cidade, "tipo": taxa.tipo,
            "valor_configurado": taxa.valor, "valor_aplicado": round(valor_taxa, 2),
        })

    # Taxa de balsa — direcional (cidade_origem -> cidade_destino nessa
    # ordem exata): só entra se essa travessia específica estiver
    # cadastrada; ida e volta são cotações independentes, porque o preço
    # da balsa pode ser diferente em cada sentido.
    custo_balsa = 0.0
    detalhe_balsa = None
    balsa_outro_veiculo = []
    taxa_balsa = _taxa_balsa_aplicavel(p, cidade_origem, cidade_destino, v.nome)
    if taxa_balsa:
        custo_balsa = _valor_taxa(taxa_balsa.tipo, taxa_balsa.valor, valor_mercadoria)
        detalhe_balsa = {
            "cidade_origem": taxa_balsa.cidade_origem, "cidade_destino": taxa_balsa.cidade_destino,
            "veiculo": taxa_balsa.veiculo, "tipo": taxa_balsa.tipo,
            "valor_configurado": taxa_balsa.valor, "valor_aplicado": round(custo_balsa, 2),
        }
    else:
        # Rota bateu (ou nem foi checada) mas não pro veículo escolhido —
        # avisa na memória de cálculo em vez de só zerar silenciosamente.
        balsa_outro_veiculo = _taxa_balsa_outros_veiculos(p, cidade_origem, cidade_destino, v.nome)

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

    frete_total = (
        frete_ajustado
        + custo_coleta
        + custo_entrega_terceirizada
        + custo_taxas_adicionais
        + custo_taxas_regionais
        + custo_balsa
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
            "percentual_capacidade_util_veiculo": v.percentual_capacidade_util,
            "capacidade_disponivel_m3_veiculo": (
                round(v.capacidade_m3 * (v.percentual_capacidade_util / 100), 4) if v.capacidade_m3 > 0 else None
            ),
            "capacidade_ocupada_pct": (
                round(volume_total_m3 / (v.capacidade_m3 * (v.percentual_capacidade_util / 100)) * 100, 1)
                if v.capacidade_m3 > 0 else None
            ),
            "tarifa_km_veiculo": tarifa_km_usada,
            "faixa_km_aplicada": faixa_km_aplicada,
            "custo_km": round(custo_km, 2),
            "peso_excedente_kg": round(peso_excedente, 3),
            "valor_tonelada_excedente": v.valor_tonelada_excedente,
            "custo_peso_excedente": round(custo_peso_excedente, 2),
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
            "distancia_manutencao_km": round(distancia + distancia_coleta_propria + distancia_retorno),
            "custo_manutencao": round(custo_manutencao, 2),
            "tarifa_km_manutencao": v.tarifa_km_manutencao,
            "custo_retorno": round(custo_retorno, 2),
            "tarifa_km_retorno": v.tarifa_km_retorno,
            "distancia_retorno_km": round(distancia_retorno),
            "taxas_adicionais": detalhe_taxas,
            "custo_taxas_adicionais": round(custo_taxas_adicionais, 2),
            "taxas_regionais": detalhe_taxas_regionais,
            "custo_taxas_regionais": round(custo_taxas_regionais, 2),
            "taxa_balsa": detalhe_balsa,
            "custo_balsa": round(custo_balsa, 2),
            "balsa_outro_veiculo": balsa_outro_veiculo or None,
        },
        "resultado": {
            "frete_total": round(frete_total, 2),
            "prazo_estimado_dias_uteis": s.prazo_dias,
        },
    }