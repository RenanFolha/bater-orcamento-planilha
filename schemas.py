# Desenvolvedor Chefe: RenanFolha

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
    quantidade: int = Field(1, ge=1, description="Quantidade de paletes idênticos com essas mesmas dimensões — evita repetir a mesma linha várias vezes", examples=[1])


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
    prioridade_rota: str = Field("", description="Nome da filial de escala obrigatória usada no trajeto (preenchido automaticamente por /geo/distancia quando a rota bate uma prioridade de rota cadastrada) — só para exibir na memória de cálculo, não afeta o valor do frete")


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


class AtualizarPedagioHistoricoRequest(BaseModel):
    pedagio: float = Field(..., ge=0, description="Novo valor de pedágio (R$) do orçamento já salvo no histórico")


class FaixaColetaIn(BaseModel):
    de: float = Field(..., ge=0)
    ate: float = Field(..., gt=0)
    taxa_fixa: float = Field(..., ge=0)
    tarifa_km: float = Field(0, ge=0)
    observacao: str = ""


class FaixaKmVeiculoIn(BaseModel):
    veiculo: str = Field(..., min_length=1, description="Veículo ao qual essa faixa se aplica (ver /parametros/veiculos)")
    de: float = Field(..., ge=0, description="Distância mínima (km) pra essa faixa valer")
    ate: float = Field(..., gt=0, description="Distância máxima (km) da faixa")
    tarifa_km: float = Field(..., ge=0, description="R$/km cobrado nessa faixa — substitui o tarifa_km fixo do veículo quando a distância do frete cair nela")
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
    uf: str = Field("", description="UF (sigla) onde a filial fica — usada pelo cálculo de ICMS quando a origem/destino do frete é essa filial")


class VeiculoIn(BaseModel):
    nome: str = Field(..., min_length=1)
    de: float = Field(0, ge=0, description="Peso mínimo (kg) para este veículo ser escolhido automaticamente")
    ate: float = Field(999999, gt=0, description="Peso máximo (kg) — acima disso, cai no próximo veículo")
    tarifa_km: float = Field(..., ge=0)
    valor_tonelada_excedente: float = Field(
        0, ge=0,
        description="R$ por TONELADA de sobrepeso além do 'até' deste veículo — só cobra quando a carga "
                     "ultrapassa até o maior veículo cadastrado (ver /orcamento)",
    )
    tarifa_km_retorno: float = Field(0, ge=0, description="R$/km do retorno vazio (destino → filial mais próxima)")
    tarifa_km_manutencao: float = Field(0, ge=0, description="R$/km de manutenção, sobre toda distância rodada pela frota própria (ida + coleta não terceirizada + retorno vazio, quando houver)")
    capacidade_m3: float = Field(
        0, ge=0,
        description="Capacidade útil de carga do veículo em m³ — a carga não pode ultrapassar o percentual "
                     "configurado (percentual_capacidade_util) desse valor (0 = sem limite de volume configurado)",
    )
    percentual_capacidade_util: float = Field(
        80, gt=0, le=100,
        description="% de capacidade_m3 que pode realmente ser ocupada (o resto fica de margem — carga não "
                     "empilha 100% perfeita, precisa espaço pra amarração etc.)",
    )
    numero_eixos: int = Field(
        0, ge=0,
        description="Número de eixos do veículo — usado pra achar o preço certo nas praças de pedágio "
                     "cadastradas (/admin/pracas-pedagio); 0 = não cadastrado, o veículo fica de fora do "
                     "cálculo automático de pedágio",
    )
    observacao: str = ""


class TaxaAdicionalIn(BaseModel):
    nome: str = Field(..., min_length=1)
    tipo: str = Field(..., pattern="^(fixo|percentual)$", description="'fixo' (R$) ou 'percentual' (% do valor da mercadoria)")
    valor: float = Field(..., ge=0)
    observacao: str = ""


class TaxaRegionalIn(BaseModel):
    cidade: str = Field(
        ..., min_length=1,
        description="Cidade(s) onde a taxa se aplica — uma ou mais separadas por vírgula (ex: 'Manaus, Boa Vista'), todas com o mesmo valor",
    )
    nome: str = Field(..., min_length=1)
    tipo: str = Field("fixo", pattern="^(fixo|percentual)$", description="'fixo' (R$) ou 'percentual' (% do valor da mercadoria)")
    valor: float = Field(..., ge=0)
    observacao: str = ""


class TaxaBalsaIn(BaseModel):
    cidade_origem: str = Field(..., min_length=1, description="Cidade de origem da travessia, ou '*' pra valer de qualquer origem (corredor fluvial, ex: qualquer UF → Manaus)")
    cidade_destino: str = Field(..., min_length=1, description="Cidade de destino da travessia — direcional: só se aplica nesse sentido (cadastre outra linha pra volta, se o valor for diferente). Também aceita '*'")
    veiculo: str = Field(..., min_length=1, description="Veículo ao qual esse valor se aplica (ver /parametros/veiculos) — a balsa pode cobrar diferente por categoria de veículo. Também aceita '*' pra valer de qualquer veículo. Quando mais de uma linha bate na mesma rota, vence a mais específica (menos curingas)")
    tipo: str = Field("fixo", pattern="^(fixo|percentual)$", description="'fixo' (R$) ou 'percentual' (% do valor da mercadoria)")
    valor: float = Field(..., ge=0)
    observacao: str = ""


class PrioridadeRotaIn(BaseModel):
    estado_origem: str = Field(..., min_length=1, description="UF de origem da rota (ex: 'SP'), ou '*' pra valer de qualquer estado")
    cidade_destino: str = Field(..., min_length=1, description="Cidade de destino da rota — direcional. Também aceita '*'")
    filial_escala: str = Field(..., min_length=1, description="Filial cadastrada por onde a rota é obrigada a passar antes do destino (ver /parametros/filiais) — a distância do frete passa a ser origem→filial + filial→destino")
    observacao: str = ""


class AliquotaIcmsIn(BaseModel):
    estado_origem: str = Field(..., min_length=1, description="UF de origem da rota (ex: 'SP'), ou '*' pra valer de qualquer estado")
    estado_destino: str = Field(..., min_length=1, description="UF de destino da rota (ex: 'RJ'), ou '*' pra valer de qualquer estado")
    aliquota: float = Field(..., ge=0, lt=100, description="Alíquota de ICMS em % — aplicada 'por dentro' (gross-up) sobre o frete total já calculado")
    observacao: str = ""


class PracaPedagioIn(BaseModel):
    nome: str = Field(..., min_length=1, description="Nome da praça de pedágio (ex: 'Praça 5 - km 123')")
    rodovia: str = Field(..., min_length=1, description="Rodovia onde fica a praça (ex: 'BR-101')")
    concessionaria: str = Field(..., min_length=1, description="Concessionária responsável pela rodovia")
    uf: str = ""
    km: str = Field("", description="Km da rodovia onde fica a praça — texto livre, só informativo")
    valor_eixo_2: float = Field(0, ge=0, description="Preço pra veículos de 2 eixos")
    valor_eixo_3: float = Field(0, ge=0, description="Preço pra veículos de 3 eixos")
    valor_eixo_4: float = Field(0, ge=0, description="Preço pra veículos de 4 eixos")
    valor_eixo_5: float = Field(0, ge=0, description="Preço pra veículos de 5 eixos")
    valor_eixo_6: float = Field(0, ge=0, description="Preço pra veículos de 6 eixos")
    valor_eixo_7: float = Field(0, ge=0, description="Preço pra veículos de 7 eixos")
    valor_eixo_8: float = Field(0, ge=0, description="Preço pra veículos de 8 eixos")
    valor_eixo_9: float = Field(0, ge=0, description="Preço pra veículos de 9 eixos")
    observacao: str = ""


class PedagioRotaIn(BaseModel):
    cidade_origem: str = Field(
        ..., min_length=1,
        description="Cidade de origem do corredor, ou '*' pra valer de qualquer origem",
    )
    cidade_destino: str = Field(
        ..., min_length=1,
        description="Cidade de destino do corredor — direcional: só se aplica nesse sentido (cadastre outra "
                     "linha pra volta, se as praças forem diferentes). Também aceita '*'",
    )
    praca_id: int = Field(..., description="Praça de pedágio (ver /admin/pracas-pedagio) que esse corredor atravessa")
    observacao: str = ""


class DistanciaFixaIn(BaseModel):
    cidade_origem: str = Field(
        ..., min_length=1,
        description="Cidade de origem do corredor, ou '*' pra valer de qualquer origem",
    )
    cidade_destino: str = Field(
        ..., min_length=1,
        description="Cidade de destino do corredor — direcional. Também aceita '*'",
    )
    distancia_km: float = Field(
        ..., gt=0,
        description="Distância (km) a usar pra esse corredor no lugar do cálculo automático (rodoviário via "
                     "OSRM/Google) — útil quando a rota real usada na prática (ex: com travessia de balsa) é "
                     "bem diferente da rota 100% rodoviária que o serviço de mapa calcularia",
    )
    observacao: str = ""


class BancoDadosConfigIn(BaseModel):
    tipo: str = Field(
        ..., pattern="^(sqlite|sqlserver|mysql|postgresql)$",
        description="Tipo de banco: 'sqlite' (arquivo local, padrão), 'sqlserver', 'mysql' ou 'postgresql'",
    )
    sqlite_path: str = Field("", description="Caminho do arquivo .db — só usado quando tipo == 'sqlite'")
    host: str = ""
    porta: int = Field(0, ge=0, le=65535)
    banco: str = ""
    usuario: str = ""
    senha: str = ""


class ImportarPracasPedagioRequest(BaseModel):
    conteudo: str = Field(
        ..., min_length=1,
        description="Conteúdo bruto do CSV (texto do arquivo lido no navegador) — ver "
                     "frete_db.importar_pracas_pedagio_csv para o formato esperado",
    )


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
