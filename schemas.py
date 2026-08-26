"""
Modelos Pydantic (corpo de requisição) usados pelas rotas da API.
Centralizados aqui para main.py e os routers não precisarem duplicar
definição de schema.
"""

from pydantic import BaseModel, Field


class PaleteIn(BaseModel):
    comprimento: float = Field(..., gt=0, description="Comprimento do palete em cm", examples=[40])
    largura: float = Field(..., gt=0, description="Largura do palete em cm", examples=[30])
    altura: float = Field(..., gt=0, description="Altura do palete em cm", examples=[25])


class OrcamentoRequest(BaseModel):
    peso: float = Field(..., gt=0, description="Peso real da mercadoria em kg", examples=[8])
    paletes: list[PaleteIn] = Field(
        ..., min_length=1,
        description="Paletes/volumes da carga — cada um com comprimento, largura e altura em cm",
    )
    distancia: float = Field(..., ge=0, description="Distância do frete principal, em km (origem efetiva → destino)", examples=[350])
    distancia_coleta: float = Field(0, ge=0, description="Distância de coleta em km (só quando há retirada no cliente com frota própria)", examples=[0])
    cidade_coleta: str = Field("", description="Endereço/cidade resolvidos da retirada — usado para checar preço fixo por cidade")
    cidade_origem: str = Field("", description="Cidade (ou nome de filial) de origem do frete — usada para checar taxas regionais")
    cidade_destino: str = Field("", description="Cidade (ou nome de filial) de destino do frete — usada para checar taxas regionais")
    valor_mercadoria: float = Field(..., ge=0, description="Valor declarado da mercadoria em R$", examples=[1200])
    categoria: str = Field(..., description="Categoria do produto (ver /parametros/categorias)", examples=["Geral"])
    transporte: str = Field(..., description="Método de transporte (ver /parametros/transportes)", examples=["Rodoviário"])
    sla: str = Field(..., description="Nível de serviço (ver /parametros/slas)", examples=["Padrão"])
    coleta_terceirizada: bool = Field(False, description="Se a coleta no cliente é feita por transportadora terceirizada (em vez de frota própria)")
    transportadora_coleta_nome: str = Field("", description="Nome da transportadora terceirizada usada na coleta")
    valor_coleta_terceirizada: float = Field(0, ge=0, description="Valor combinado com a transportadora para a coleta")
    entrega_terceirizada: bool = Field(False, description="Se a entrega final ao cliente é feita por transportadora terceirizada (em vez de frota própria)")
    transportadora_entrega_nome: str = Field("", description="Nome da transportadora terceirizada usada na entrega")
    valor_entrega_terceirizada: float = Field(0, ge=0, description="Valor combinado com a transportadora para a entrega")
    pedagio: float = Field(0, ge=0, description="Valor estimado de pedágio da rota em R$ (preenchido automaticamente pelo Google Maps quando disponível, editável)")
    distancia_retorno: float = Field(0, ge=0, description="Distância (km) do retorno vazio do veículo, do destino até a filial mais próxima — só quando a entrega é feita direto ao cliente pela frota própria")


class DistanciaRequest(BaseModel):
    origem: str = Field(..., description="Endereço de origem", examples=["Av. Paulista, 1000, São Paulo, SP"])
    destino: str = Field(..., description="Endereço de destino", examples=["Rua XV de Novembro, 500, Curitiba, PR"])
    peso: float = Field(0, ge=0, description="Peso real da carga em kg — opcional, só usado pra descobrir o veículo e permitir reaproveitar a distância de uma rota+veículo já cotada no histórico")
    paletes: list[PaleteIn] = Field(default_factory=list, description="Paletes/volumes da carga — mesmo uso do campo peso, opcional")
    transporte: str = Field("", description="Método de transporte (ver /parametros/transportes) — mesmo uso do campo peso, opcional")


class RetiradaRequest(BaseModel):
    endereco_retirada: str = Field(..., description="Endereço onde a carga será retirada com o cliente", examples=["Rua Augusta, 500, São Paulo, SP"])


class EntregaRequest(BaseModel):
    endereco_entrega: str = Field(..., description="Endereço onde a carga será entregue ao cliente", examples=["Rua Augusta, 500, São Paulo, SP"])


class RetornoRequest(BaseModel):
    endereco_destino: str = Field(..., description="Endereço final da entrega — usado para achar a filial mais próxima pra onde o veículo volta vazio", examples=["Rua Augusta, 500, São Paulo, SP"])


class HistoricoSalvarRequest(BaseModel):
    cliente: str = Field(..., min_length=1, description="Nome do cliente/empresa do orçamento")
    responsavel: str = Field(..., min_length=1, description="Quem fez o orçamento")
    origem_resumo: str = ""
    destino_resumo: str = ""
    veiculo: str = ""
    distancia_km: float = 0
    valor_mercadoria: float = 0
    frete_total: float = 0
    dados: dict = Field(default_factory=dict, description="Snapshot completo do orçamento (entrada + resultado) para consulta posterior")


class FaixaColetaIn(BaseModel):
    de: float = Field(..., ge=0)
    ate: float = Field(..., gt=0)
    taxa_fixa: float = Field(..., ge=0)
    tarifa_km: float = Field(0, ge=0)
    observacao: str = ""


class CategoriaIn(BaseModel):
    nome: str = Field(..., min_length=1)
    multiplicador: float = Field(..., gt=0)
    observacao: str = ""


class TransporteIn(BaseModel):
    nome: str = Field(..., min_length=1)
    multiplicador: float = Field(..., gt=0)
    fator_cubagem: float = Field(..., gt=0)
    observacao: str = ""


class SlaIn(BaseModel):
    nome: str = Field(..., min_length=1)
    multiplicador: float = Field(..., gt=0)
    prazo_dias: int = Field(..., ge=0)
    observacao: str = ""


class FilialIn(BaseModel):
    nome: str = Field(..., min_length=1)
    endereco: str = Field(..., min_length=1)


class VeiculoIn(BaseModel):
    nome: str = Field(..., min_length=1)
    de: float = Field(0, ge=0, description="Peso mínimo (kg) para este veículo ser escolhido automaticamente")
    ate: float = Field(999999, gt=0, description="Peso máximo (kg) — acima disso, cai no próximo veículo")
    tarifa_km: float = Field(..., ge=0)
    peso_incluso_kg: float = Field(0, ge=0)
    valor_kg_excedente: float = Field(0, ge=0)
    tarifa_km_retorno: float = Field(0, ge=0, description="R$/km do retorno vazio (destino → filial mais próxima)")
    tarifa_km_manutencao: float = Field(0, ge=0, description="R$/km de manutenção, sobre a distância de ida")
    capacidade_m3: float = Field(
        0, ge=0,
        description="Capacidade útil de carga do veículo em m³ — a carga não pode ultrapassar 80% desse "
                     "valor (0 = sem limite de volume configurado)",
    )
    observacao: str = ""


class TaxaAdicionalIn(BaseModel):
    nome: str = Field(..., min_length=1)
    tipo: str = Field(..., pattern="^(fixo|percentual)$", description="'fixo' (R$) ou 'percentual' (% do valor da mercadoria)")
    valor: float = Field(..., ge=0)
    observacao: str = ""


class TaxaRegionalIn(BaseModel):
    cidade: str = Field(..., min_length=1)
    nome: str = Field(..., min_length=1)
    tipo: str = Field("fixo", pattern="^(fixo|percentual)$", description="'fixo' (R$) ou 'percentual' (% do valor da mercadoria)")
    valor: float = Field(..., ge=0)
    observacao: str = ""


class ColetaCidadeFixaIn(BaseModel):
    filial_origem: str = Field(..., min_length=1, description="Filial de onde o veículo sai para fazer a coleta (ver /parametros/filiais)")
    cidade_destino: str = Field(
        ..., min_length=1,
        description="Cidade(s) onde a coleta é feita (endereço do cliente) — uma ou mais, separadas por vírgula "
                     "(ex: 'Osasco, Barueri, Cotia'), todas com o mesmo preço fixo",
    )
    veiculo: str = Field(..., min_length=1, description="Veículo ao qual esse preço fixo se aplica (ver /parametros/veiculos)")
    valor_fixo: float = Field(..., ge=0)
    observacao: str = ""


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    senha: str = Field(..., min_length=1)


# Tamanho mínimo de senha exigido em toda a API (troca de senha, criação e
# edição de usuário) — 4 caracteres era fraco demais para um sistema com
# dados de clientes e preços; 8 é o piso razoável sem exigir dependência
# externa de política de senha.
SENHA_MIN_LENGTH = 8


class TrocarSenhaRequest(BaseModel):
    senha_atual: str = Field(..., min_length=1)
    senha_nova: str = Field(..., min_length=SENHA_MIN_LENGTH)


class UsuarioIn(BaseModel):
    nome: str = Field(..., min_length=1)
    username: str = Field(..., min_length=3)
    senha: str = Field(..., min_length=SENHA_MIN_LENGTH)
    role: str = Field(..., pattern="^(admin|usuario)$")
    ativo: bool = True


class UsuarioUpdateIn(BaseModel):
    nome: str = Field(..., min_length=1)
    username: str = Field(..., min_length=3)
    role: str = Field(..., pattern="^(admin|usuario)$")
    ativo: bool = True
    senha: str = Field("", description="Deixe em branco para manter a senha atual")


class TransportadoraTerceirizadaIn(BaseModel):
    nome: str = Field(..., min_length=1)
    cidade: str = Field(..., min_length=1)
    tipo: str = Field("ambos", pattern="^(coleta|entrega|ambos)$", description="'coleta', 'entrega' ou 'ambos'")
    valor: float = Field(..., ge=0, description="Valor combinado em R$")
    observacao: str = ""
