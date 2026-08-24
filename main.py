"""
API de Orçamento de Frete

Lê as regras de precificação do banco SQLite (frete.db) e expõe
endpoints para calcular o frete, resolver endereços/filiais e recarregar
os parâmetros depois de editar o banco.

Rodar localmente:
    python main.py
    (ou) uvicorn main:app --reload --port 8000

Documentação interativa (Swagger):
    http://localhost:8000/docs
"""

from contextlib import asynccontextmanager
from pathlib import Path
import json
import sqlite3

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import auth_service as auth
import export_service as export
import frete_db as db
import frete_service as fs
import geo_service as geo


BASE_DIR = Path(__file__).resolve().parent
INDEX_PATH = BASE_DIR / "index.html"
ASSETS_DIR = BASE_DIR / "assets"
FAVICON_PATH = ASSETS_DIR / "favicon-16x16.png"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()  # garante que o banco/tabelas existem (não sobrescreve dados) — só roda aqui, uma vez
    fs.carregar_parametros()
    auth.garantir_usuario_padrao()
    yield


app = FastAPI(
    title="API de Orçamento de Frete",
    description="Calcula o frete a partir das regras cadastradas no banco frete.db",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,  # necessário pro cookie de sessão de login
    allow_methods=["*"],
    allow_headers=["*"],
)

if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")

COOKIE_SESSAO = "frete_session"


def usuario_atual(request: Request) -> dict | None:
    return auth.validar_sessao(request.cookies.get(COOKIE_SESSAO))


def exigir_login(usuario: dict | None = Depends(usuario_atual)) -> dict:
    if not usuario:
        raise HTTPException(status_code=401, detail="Faça login para continuar.")
    return usuario


def exigir_admin(usuario: dict = Depends(exigir_login)) -> dict:
    if usuario["role"] != "admin":
        raise HTTPException(status_code=403, detail="Ação restrita a administradores.")
    return usuario


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
    cidade_destino: str = Field(..., min_length=1, description="Cidade onde a coleta é feita (endereço do cliente)")
    veiculo: str = Field(..., min_length=1, description="Veículo ao qual esse preço fixo se aplica (ver /parametros/veiculos)")
    valor_fixo: float = Field(..., ge=0)
    observacao: str = ""


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    senha: str = Field(..., min_length=1)


class TrocarSenhaRequest(BaseModel):
    senha_atual: str = Field(..., min_length=1)
    senha_nova: str = Field(..., min_length=4)


class UsuarioIn(BaseModel):
    nome: str = Field(..., min_length=1)
    username: str = Field(..., min_length=3)
    senha: str = Field(..., min_length=4)
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


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    if not FAVICON_PATH.exists():
        raise HTTPException(status_code=404, detail="Favicon nao encontrado.")
    return FileResponse(FAVICON_PATH)


@app.get("/", include_in_schema=False)
def raiz():
    if not INDEX_PATH.exists():
        raise HTTPException(status_code=500, detail="Arquivo index.html não encontrado.")
    return FileResponse(INDEX_PATH)


@app.get("/orçamentos", include_in_schema=False)
def orcamentos_web():
    if not INDEX_PATH.exists():
        raise HTTPException(status_code=500, detail="Arquivo index.html não encontrado.")
    return FileResponse(INDEX_PATH)


@app.get("/api/status", tags=["Status"])
def status():
    return {
        "status": "ok",
        "servico": "API de Orçamento de Frete",
        "versao": app.version,
        "banco": str(db.DB_PATH),
        "geo_provider": "google" if geo.usando_google() else "osm",
    }


@app.get("/health", tags=["Status"])
def health():
    return {"status": "ok"}


@app.post("/auth/login", tags=["Autenticação"])
def login(payload: LoginRequest, request: Request, response: Response):
    ip = request.client.host if request.client else "desconhecido"
    espera = auth.login_bloqueado(ip)
    if espera:
        raise HTTPException(
            status_code=429,
            detail=f"Muitas tentativas de login falhas. Tente novamente em {espera // 60 + 1} minuto(s).",
            headers={"Retry-After": str(espera)},
        )

    usuario = auth.autenticar(payload.username, payload.senha)
    if not usuario:
        auth.registrar_tentativa_falha(ip)
        raise HTTPException(status_code=401, detail="Usuário ou senha inválidos.")
    auth.limpar_tentativas_falha(ip)
    token = auth.criar_sessao(usuario["id"])
    response.set_cookie(
        COOKIE_SESSAO, token, httponly=True, samesite="lax",
        max_age=auth.SESSAO_DURACAO_HORAS * 3600, path="/",
    )
    return {"id": usuario["id"], "nome": usuario["nome"], "username": usuario["username"], "role": usuario["role"]}


@app.post("/auth/logout", tags=["Autenticação"])
def logout(request: Request, response: Response):
    auth.encerrar_sessao(request.cookies.get(COOKIE_SESSAO))
    response.delete_cookie(COOKIE_SESSAO, path="/")
    return {"status": "ok"}


@app.get("/auth/me", tags=["Autenticação"])
def me(usuario: dict = Depends(exigir_login)):
    return usuario


@app.post("/auth/trocar-senha", tags=["Autenticação"])
def trocar_senha(payload: TrocarSenhaRequest, usuario: dict = Depends(exigir_login)):
    if not auth.autenticar(usuario["username"], payload.senha_atual):
        raise HTTPException(status_code=401, detail="Senha atual incorreta.")
    senha_hash, senha_salt = auth.gerar_hash_senha(payload.senha_nova)
    db.atualizar_senha_usuario(usuario["id"], senha_hash, senha_salt)
    return {"status": "ok"}


@app.post("/orcamento", tags=["Orçamento"])
def orcamento(payload: OrcamentoRequest):
    try:
        return fs.calcular_orcamento(
            peso=payload.peso,
            paletes=[p.model_dump() for p in payload.paletes],
            distancia=payload.distancia,
            distancia_coleta=payload.distancia_coleta,
            cidade_coleta=payload.cidade_coleta or None,
            cidade_origem=payload.cidade_origem or None,
            cidade_destino=payload.cidade_destino or None,
            valor_mercadoria=payload.valor_mercadoria,
            categoria=payload.categoria,
            transporte=payload.transporte,
            sla=payload.sla,
            coleta_terceirizada=payload.coleta_terceirizada,
            transportadora_coleta_nome=payload.transportadora_coleta_nome,
            valor_coleta_terceirizada=payload.valor_coleta_terceirizada,
            entrega_terceirizada=payload.entrega_terceirizada,
            transportadora_entrega_nome=payload.transportadora_entrega_nome,
            valor_entrega_terceirizada=payload.valor_entrega_terceirizada,
            pedagio=payload.pedagio,
            distancia_retorno=payload.distancia_retorno,
        )
    except fs.FreteInputError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except fs.FreteConfigError as e:
        raise HTTPException(status_code=500, detail=f"Erro de configuração: {e}")


@app.post("/historico", tags=["Histórico"])
def salvar_historico(payload: HistoricoSalvarRequest, usuario: dict = Depends(exigir_login)):
    info = db.salvar_orcamento_historico(
        cliente=payload.cliente,
        responsavel=payload.responsavel,
        origem_resumo=payload.origem_resumo,
        destino_resumo=payload.destino_resumo,
        veiculo=payload.veiculo,
        distancia_km=payload.distancia_km,
        valor_mercadoria=payload.valor_mercadoria,
        frete_total=payload.frete_total,
        dados_json=json.dumps(payload.dados, ensure_ascii=False),
    )
    return info


@app.get("/historico", tags=["Histórico"])
def listar_historico(usuario: dict = Depends(exigir_login)):
    """Lista o histórico sem o snapshot completo (fica pesado) — use
    GET /historico/{codigo} pra ver os detalhes de um orçamento específico."""
    registros = db.listar_orcamentos_historico()
    for r in registros:
        r.pop("dados_json", None)
    return registros


@app.get("/historico/{codigo}", tags=["Histórico"])
def obter_historico(codigo: str, usuario: dict = Depends(exigir_login)):
    registro = db.buscar_orcamento_historico(codigo)
    if not registro:
        raise HTTPException(status_code=404, detail=f"Orçamento '{codigo}' não encontrado no histórico.")
    registro["dados"] = json.loads(registro.pop("dados_json") or "{}")
    return registro


@app.delete("/historico/{id_}", tags=["Histórico"])
def excluir_historico(id_: int, usuario: dict = Depends(exigir_login)):
    db.excluir_orcamento_historico(id_)
    return {"status": "ok"}


@app.get("/historico/{codigo}/planilha", tags=["Histórico"])
def exportar_historico_planilha(codigo: str, usuario: dict = Depends(exigir_login)):
    """Gera a planilha de orçamento (formato 'Modelo de Orçamento.xlsx')
    preenchida com os dados desse orçamento do histórico."""
    registro = db.buscar_orcamento_historico(codigo)
    if not registro:
        raise HTTPException(status_code=404, detail=f"Orçamento '{codigo}' não encontrado no histórico.")
    registro["dados"] = json.loads(registro.pop("dados_json") or "{}")
    try:
        conteudo = export.gerar_planilha_orcamento(registro)
    except export.ExportacaoError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return Response(
        content=conteudo,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="Orcamento_{codigo}.xlsx"'},
    )


@app.post("/geo/distancia", tags=["Geolocalização"])
async def distancia_por_endereco(payload: DistanciaRequest):
    """Geocodifica os dois endereços (ou endereços de filiais) e calcula a
    distância rodoviária entre eles (em km). Usado para o trecho principal
    do frete (origem efetiva → destino)."""
    try:
        return await geo.calcular_distancia(payload.origem, payload.destino)
    except geo.GeoError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.post("/geo/resolver-retirada", tags=["Geolocalização"])
async def resolver_retirada(payload: RetiradaRequest):
    """Dado um endereço de retirada no cliente, encontra a filial cadastrada
    mais próxima e calcula a distância de coleta (filial → endereço)."""
    try:
        filiais = list(fs.parametros.filiais.values())
        return await geo.resolver_retirada(payload.endereco_retirada, filiais)
    except geo.GeoError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.post("/geo/resolver-entrega", tags=["Geolocalização"])
async def resolver_entrega(payload: EntregaRequest):
    """Dado um endereço de entrega no cliente, encontra a filial cadastrada
    mais próxima. Usado quando a entrega final é terceirizada: a rota
    principal (frota própria) vai só até essa filial, e o trecho
    filial → cliente fica por conta da transportadora contratada."""
    try:
        filiais = list(fs.parametros.filiais.values())
        return await geo.resolver_retirada(payload.endereco_entrega, filiais)
    except geo.GeoError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.post("/geo/resolver-retorno", tags=["Geolocalização"])
async def resolver_retorno(payload: RetornoRequest):
    """Dado o endereço final da entrega, encontra a filial cadastrada mais
    próxima pra onde o veículo (vazio) precisa voltar depois de entregar —
    usado pra estimar o custo do retorno vazio. Sempre precisa ser
    confirmado na tela antes de entrar no orçamento, porque o veículo
    pode não voltar exatamente pra filial mais próxima geograficamente."""
    try:
        filiais = list(fs.parametros.filiais.values())
        return await geo.resolver_retirada(payload.endereco_destino, filiais)
    except geo.GeoError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.get("/parametros/categorias", tags=["Parâmetros"])
def listar_categorias():
    return [
        {"nome": c.nome, "multiplicador": c.multiplicador}
        for c in fs.parametros.categorias.values()
    ]


@app.get("/parametros/transportes", tags=["Parâmetros"])
def listar_transportes():
    return [
        {"nome": t.nome, "multiplicador": t.multiplicador, "fator_cubagem": t.fator_cubagem}
        for t in fs.parametros.transportes.values()
    ]


@app.get("/parametros/slas", tags=["Parâmetros"])
def listar_slas():
    return [
        {"nome": s.nome, "multiplicador": s.multiplicador, "prazo_dias": s.prazo_dias}
        for s in fs.parametros.slas.values()
    ]


@app.get("/parametros/filiais", tags=["Parâmetros"])
def listar_filiais():
    return [
        {"nome": f.nome, "endereco": f.endereco}
        for f in fs.parametros.filiais.values()
    ]


@app.get("/parametros/veiculos", tags=["Parâmetros"])
def listar_veiculos():
    return [
        {
            "nome": v.nome, "de": v.de, "ate": v.ate, "tarifa_km": v.tarifa_km,
            "peso_incluso_kg": v.peso_incluso_kg, "valor_kg_excedente": v.valor_kg_excedente,
        }
        for v in fs.parametros.veiculos.values()
    ]


@app.get("/parametros/taxas-adicionais", tags=["Parâmetros"])
def listar_taxas_adicionais_publico():
    return [
        {"nome": t.nome, "tipo": t.tipo, "valor": t.valor}
        for t in fs.parametros.taxas_adicionais
    ]


@app.get("/parametros/tipos-frete", tags=["Parâmetros"])
def listar_tipos_frete():
    """Endpoint legado, mantido para compatibilidade com integrações que
    ainda leem as tabelas antigas de tipo de frete (faixas_peso/
    faixas_distancia) — não é mais usado no cálculo de orçamento, que
    hoje é baseado em veículo (ver /parametros/veiculos)."""
    tipos = {r["tipo_frete"] for r in db.listar_faixas_peso()}
    tipos |= {r["tipo_frete"] for r in db.listar_faixas_distancia()}
    return sorted(tipos)


@app.get("/parametros/faixas-peso", tags=["Parâmetros"])
def listar_faixas_peso_publico(tipo_frete: str | None = None):
    """Endpoint legado — ver nota em /parametros/tipos-frete."""
    faixas = db.listar_faixas_peso()
    if tipo_frete:
        faixas = [f for f in faixas if f["tipo_frete"] == tipo_frete]
    return [
        {
            "tipo_frete": f["tipo_frete"], "de": f["de"], "ate": f["ate"],
            "tarifa_base": f["tarifa_base"], "custo_kg_adicional": f["custo_kg_adicional"],
        }
        for f in faixas
    ]


@app.get("/parametros/faixas-distancia", tags=["Parâmetros"])
def listar_faixas_distancia_publico(tipo_frete: str | None = None):
    """Endpoint legado — ver nota em /parametros/tipos-frete."""
    faixas = db.listar_faixas_distancia()
    if tipo_frete:
        faixas = [f for f in faixas if f["tipo_frete"] == tipo_frete]
    return [
        {
            "tipo_frete": f["tipo_frete"], "de": f["de"], "ate": f["ate"],
            "taxa_fixa": f["taxa_fixa"], "tarifa_km": f["tarifa_km"],
        }
        for f in faixas
    ]


@app.get("/parametros/faixas-coleta", tags=["Parâmetros"])
def listar_faixas_coleta():
    return [
        {"de": f.de, "ate": f.ate, "taxa_fixa": f.taxa_fixa, "tarifa_km": f.tarifa_km}
        for f in fs.parametros.faixas_coleta
    ]


@app.get("/parametros/transportadoras-terceirizadas", tags=["Parâmetros"])
def listar_transportadoras_terceirizadas():
    """Lista as transportadoras terceirizadas cadastradas — usado pra
    montar o seletor na tela de orçamento quando coleta/entrega é
    terceirizada."""
    return db.listar_transportadoras_terceirizadas_admin()


@app.post("/admin/reload", tags=["Admin"])
def reload_parametros(usuario: dict = Depends(exigir_admin)):
    """Recarrega os parâmetros direto do banco SQLite.
    Use depois de editar o frete.db (ex: com o DB Browser for SQLite),
    sem precisar reiniciar a API."""
    try:
        fs.carregar_parametros()
        return {"status": "ok", "mensagem": "Parâmetros recarregados a partir do banco."}
    except fs.FreteConfigError as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# CRUD da tela "Tabela de Preços" — cada escrita recarrega o cache
# de parâmetros em memória, então o cálculo de frete já reflete a
# mudança na hora, sem precisar chamar /admin/reload manualmente.
#
# Os handlers abaixo delegam para _admin_criar/_admin_atualizar/
# _admin_excluir: cada rota continua explícita (uma função por tabela,
# sem despachar por nome de tabela vindo do payload) para manter o
# schema do OpenAPI e evitar SQL dinâmico a partir de entrada do
# usuário — só o try/except de conflito e o reload pós-escrita, que
# eram idênticos em ~40 handlers, foram centralizados.
# ============================================================

def _admin_criar(inserir_fn, payload: BaseModel, msg_conflito: str, reload: bool = True) -> dict:
    try:
        novo_id = inserir_fn(**payload.model_dump())
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail=msg_conflito)
    if reload:
        fs.carregar_parametros()
    return {"id": novo_id}


def _admin_atualizar(atualizar_fn, id_: int, payload: BaseModel, msg_conflito: str, reload: bool = True) -> dict:
    try:
        atualizar_fn(id_, **payload.model_dump())
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail=msg_conflito)
    if reload:
        fs.carregar_parametros()
    return {"status": "ok"}


def _admin_excluir(excluir_fn, id_: int, contar_fn=None, msg_ultimo: str = "", reload: bool = True) -> dict:
    if contar_fn is not None and contar_fn() <= 1:
        raise HTTPException(status_code=422, detail=msg_ultimo)
    excluir_fn(id_)
    if reload:
        fs.carregar_parametros()
    return {"status": "ok"}


@app.get("/admin/filiais", tags=["Admin - Tabela de Preços"])
def admin_listar_filiais(usuario: dict = Depends(exigir_admin)):
    return db.listar_filiais_admin()


@app.post("/admin/filiais", tags=["Admin - Tabela de Preços"])
def admin_criar_filial(payload: FilialIn, usuario: dict = Depends(exigir_admin)):
    return _admin_criar(db.inserir_filial, payload, f"Já existe uma filial chamada '{payload.nome}'.")


@app.put("/admin/filiais/{id_}", tags=["Admin - Tabela de Preços"])
def admin_atualizar_filial(id_: int, payload: FilialIn, usuario: dict = Depends(exigir_admin)):
    return _admin_atualizar(db.atualizar_filial, id_, payload, f"Já existe uma filial chamada '{payload.nome}'.")


@app.delete("/admin/filiais/{id_}", tags=["Admin - Tabela de Preços"])
def admin_excluir_filial(id_: int, usuario: dict = Depends(exigir_admin)):
    return _admin_excluir(
        db.excluir_filial, id_, db.contar_filiais,
        "Não é possível excluir a última filial cadastrada — o sistema precisa de pelo menos uma.",
    )


@app.get("/admin/veiculos", tags=["Admin - Tabela de Preços"])
def admin_listar_veiculos(usuario: dict = Depends(exigir_admin)):
    return db.listar_veiculos_admin()


@app.post("/admin/veiculos", tags=["Admin - Tabela de Preços"])
def admin_criar_veiculo(payload: VeiculoIn, usuario: dict = Depends(exigir_admin)):
    return _admin_criar(db.inserir_veiculo, payload, f"Já existe um veículo chamado '{payload.nome}'.")


@app.put("/admin/veiculos/{id_}", tags=["Admin - Tabela de Preços"])
def admin_atualizar_veiculo(id_: int, payload: VeiculoIn, usuario: dict = Depends(exigir_admin)):
    return _admin_atualizar(db.atualizar_veiculo, id_, payload, f"Já existe um veículo chamado '{payload.nome}'.")


@app.delete("/admin/veiculos/{id_}", tags=["Admin - Tabela de Preços"])
def admin_excluir_veiculo(id_: int, usuario: dict = Depends(exigir_admin)):
    return _admin_excluir(
        db.excluir_veiculo, id_, db.contar_veiculos,
        "Não é possível excluir o último veículo cadastrado — o sistema precisa de pelo menos um.",
    )


@app.get("/admin/taxas-adicionais", tags=["Admin - Tabela de Preços"])
def admin_listar_taxas_adicionais(usuario: dict = Depends(exigir_admin)):
    return db.listar_taxas_adicionais_admin()


@app.post("/admin/taxas-adicionais", tags=["Admin - Tabela de Preços"])
def admin_criar_taxa_adicional(payload: TaxaAdicionalIn, usuario: dict = Depends(exigir_admin)):
    return _admin_criar(db.inserir_taxa_adicional, payload, f"Já existe uma taxa chamada '{payload.nome}'.")


@app.put("/admin/taxas-adicionais/{id_}", tags=["Admin - Tabela de Preços"])
def admin_atualizar_taxa_adicional(id_: int, payload: TaxaAdicionalIn, usuario: dict = Depends(exigir_admin)):
    return _admin_atualizar(db.atualizar_taxa_adicional, id_, payload, f"Já existe uma taxa chamada '{payload.nome}'.")


@app.delete("/admin/taxas-adicionais/{id_}", tags=["Admin - Tabela de Preços"])
def admin_excluir_taxa_adicional(id_: int, usuario: dict = Depends(exigir_admin)):
    return _admin_excluir(db.excluir_taxa_adicional, id_)


@app.get("/admin/coleta-cidades-fixas", tags=["Admin - Tabela de Preços"])
def admin_listar_coleta_cidades_fixas(usuario: dict = Depends(exigir_admin)):
    return db.listar_coleta_cidades_fixas_admin()


@app.post("/admin/coleta-cidades-fixas", tags=["Admin - Tabela de Preços"])
def admin_criar_coleta_cidade_fixa(payload: ColetaCidadeFixaIn, usuario: dict = Depends(exigir_admin)):
    return _admin_criar(
        db.inserir_coleta_cidade_fixa, payload,
        f"Já existe um preço fixo de coleta de '{payload.filial_origem}' → "
        f"'{payload.cidade_destino}' no veículo '{payload.veiculo}'.",
    )


@app.put("/admin/coleta-cidades-fixas/{id_}", tags=["Admin - Tabela de Preços"])
def admin_atualizar_coleta_cidade_fixa(id_: int, payload: ColetaCidadeFixaIn, usuario: dict = Depends(exigir_admin)):
    return _admin_atualizar(
        db.atualizar_coleta_cidade_fixa, id_, payload,
        f"Já existe um preço fixo de coleta de '{payload.filial_origem}' → "
        f"'{payload.cidade_destino}' no veículo '{payload.veiculo}'.",
    )


@app.delete("/admin/coleta-cidades-fixas/{id_}", tags=["Admin - Tabela de Preços"])
def admin_excluir_coleta_cidade_fixa(id_: int, usuario: dict = Depends(exigir_admin)):
    return _admin_excluir(db.excluir_coleta_cidade_fixa, id_)


@app.get("/admin/taxas-regionais", tags=["Admin - Tabela de Preços"])
def admin_listar_taxas_regionais(usuario: dict = Depends(exigir_admin)):
    return db.listar_taxas_regionais_admin()


@app.post("/admin/taxas-regionais", tags=["Admin - Tabela de Preços"])
def admin_criar_taxa_regional(payload: TaxaRegionalIn, usuario: dict = Depends(exigir_admin)):
    return _admin_criar(
        db.inserir_taxa_regional, payload,
        f"Já existe uma taxa '{payload.nome}' cadastrada para a cidade '{payload.cidade}'.",
    )


@app.put("/admin/taxas-regionais/{id_}", tags=["Admin - Tabela de Preços"])
def admin_atualizar_taxa_regional(id_: int, payload: TaxaRegionalIn, usuario: dict = Depends(exigir_admin)):
    return _admin_atualizar(
        db.atualizar_taxa_regional, id_, payload,
        f"Já existe uma taxa '{payload.nome}' cadastrada para a cidade '{payload.cidade}'.",
    )


@app.delete("/admin/taxas-regionais/{id_}", tags=["Admin - Tabela de Preços"])
def admin_excluir_taxa_regional(id_: int, usuario: dict = Depends(exigir_admin)):
    return _admin_excluir(db.excluir_taxa_regional, id_)


@app.get("/admin/transportadoras-terceirizadas", tags=["Admin - Tabela de Preços"])
def admin_listar_transportadoras_terceirizadas(usuario: dict = Depends(exigir_admin)):
    return db.listar_transportadoras_terceirizadas_admin()


@app.post("/admin/transportadoras-terceirizadas", tags=["Admin - Tabela de Preços"])
def admin_criar_transportadora_terceirizada(payload: TransportadoraTerceirizadaIn, usuario: dict = Depends(exigir_admin)):
    # reload=False: transportadoras terceirizadas não fazem parte do
    # ParametrosFrete em memória (são lidas direto do banco quando
    # usadas), então recarregar o cache aqui não teria efeito nenhum.
    return _admin_criar(db.inserir_transportadora_terceirizada, payload, "", reload=False)


@app.put("/admin/transportadoras-terceirizadas/{id_}", tags=["Admin - Tabela de Preços"])
def admin_atualizar_transportadora_terceirizada(id_: int, payload: TransportadoraTerceirizadaIn, usuario: dict = Depends(exigir_admin)):
    return _admin_atualizar(db.atualizar_transportadora_terceirizada, id_, payload, "", reload=False)


@app.delete("/admin/transportadoras-terceirizadas/{id_}", tags=["Admin - Tabela de Preços"])
def admin_excluir_transportadora_terceirizada(id_: int, usuario: dict = Depends(exigir_admin)):
    return _admin_excluir(db.excluir_transportadora_terceirizada, id_, reload=False)


@app.get("/admin/faixas-coleta", tags=["Admin - Tabela de Preços"])
def admin_listar_faixas_coleta(usuario: dict = Depends(exigir_admin)):
    return db.listar_faixas_coleta()


@app.post("/admin/faixas-coleta", tags=["Admin - Tabela de Preços"])
def admin_criar_faixa_coleta(payload: FaixaColetaIn, usuario: dict = Depends(exigir_admin)):
    return _admin_criar(db.inserir_faixa_coleta, payload, "")


@app.put("/admin/faixas-coleta/{id_}", tags=["Admin - Tabela de Preços"])
def admin_atualizar_faixa_coleta(id_: int, payload: FaixaColetaIn, usuario: dict = Depends(exigir_admin)):
    return _admin_atualizar(db.atualizar_faixa_coleta, id_, payload, "")


@app.delete("/admin/faixas-coleta/{id_}", tags=["Admin - Tabela de Preços"])
def admin_excluir_faixa_coleta(id_: int, usuario: dict = Depends(exigir_admin)):
    return _admin_excluir(
        db.excluir_faixa_coleta, id_, db.contar_faixas_coleta,
        "Não é possível excluir a última faixa de coleta cadastrada — o sistema precisa de pelo menos uma.",
    )


@app.get("/admin/categorias", tags=["Admin - Tabela de Preços"])
def admin_listar_categorias(usuario: dict = Depends(exigir_admin)):
    return db.listar_categorias_admin()


@app.post("/admin/categorias", tags=["Admin - Tabela de Preços"])
def admin_criar_categoria(payload: CategoriaIn, usuario: dict = Depends(exigir_admin)):
    return _admin_criar(db.inserir_categoria, payload, f"Já existe uma categoria chamada '{payload.nome}'.")


@app.put("/admin/categorias/{id_}", tags=["Admin - Tabela de Preços"])
def admin_atualizar_categoria(id_: int, payload: CategoriaIn, usuario: dict = Depends(exigir_admin)):
    return _admin_atualizar(db.atualizar_categoria, id_, payload, f"Já existe uma categoria chamada '{payload.nome}'.")


@app.delete("/admin/categorias/{id_}", tags=["Admin - Tabela de Preços"])
def admin_excluir_categoria(id_: int, usuario: dict = Depends(exigir_admin)):
    return _admin_excluir(
        db.excluir_categoria, id_, db.contar_categorias,
        "Não é possível excluir a última categoria cadastrada — o sistema precisa de pelo menos uma.",
    )


@app.get("/admin/transportes", tags=["Admin - Tabela de Preços"])
def admin_listar_transportes(usuario: dict = Depends(exigir_admin)):
    return db.listar_transportes_admin()


@app.post("/admin/transportes", tags=["Admin - Tabela de Preços"])
def admin_criar_transporte(payload: TransporteIn, usuario: dict = Depends(exigir_admin)):
    return _admin_criar(db.inserir_transporte, payload, f"Já existe um transporte chamado '{payload.nome}'.")


@app.put("/admin/transportes/{id_}", tags=["Admin - Tabela de Preços"])
def admin_atualizar_transporte(id_: int, payload: TransporteIn, usuario: dict = Depends(exigir_admin)):
    return _admin_atualizar(db.atualizar_transporte, id_, payload, f"Já existe um transporte chamado '{payload.nome}'.")


@app.delete("/admin/transportes/{id_}", tags=["Admin - Tabela de Preços"])
def admin_excluir_transporte(id_: int, usuario: dict = Depends(exigir_admin)):
    return _admin_excluir(
        db.excluir_transporte, id_, db.contar_transportes,
        "Não é possível excluir o último transporte cadastrado — o sistema precisa de pelo menos um.",
    )


@app.get("/admin/slas", tags=["Admin - Tabela de Preços"])
def admin_listar_slas(usuario: dict = Depends(exigir_admin)):
    return db.listar_slas_admin()


@app.post("/admin/slas", tags=["Admin - Tabela de Preços"])
def admin_criar_sla(payload: SlaIn, usuario: dict = Depends(exigir_admin)):
    return _admin_criar(db.inserir_sla, payload, f"Já existe um SLA chamado '{payload.nome}'.")


@app.put("/admin/slas/{id_}", tags=["Admin - Tabela de Preços"])
def admin_atualizar_sla(id_: int, payload: SlaIn, usuario: dict = Depends(exigir_admin)):
    return _admin_atualizar(db.atualizar_sla, id_, payload, f"Já existe um SLA chamado '{payload.nome}'.")


@app.delete("/admin/slas/{id_}", tags=["Admin - Tabela de Preços"])
def admin_excluir_sla(id_: int, usuario: dict = Depends(exigir_admin)):
    return _admin_excluir(
        db.excluir_sla, id_, db.contar_slas,
        "Não é possível excluir o último SLA cadastrado — o sistema precisa de pelo menos um.",
    )


@app.get("/admin/usuarios", tags=["Admin - Usuários"])
def admin_listar_usuarios(usuario: dict = Depends(exigir_admin)):
    return db.listar_usuarios_admin()


@app.post("/admin/usuarios", tags=["Admin - Usuários"])
def admin_criar_usuario(payload: UsuarioIn, usuario: dict = Depends(exigir_admin)):
    senha_hash, senha_salt = auth.gerar_hash_senha(payload.senha)
    try:
        novo_id = db.inserir_usuario(
            nome=payload.nome, username=payload.username,
            senha_hash=senha_hash, senha_salt=senha_salt,
            role=payload.role, ativo=payload.ativo,
        )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail=f"Já existe um usuário com o login '{payload.username}'.")
    return {"id": novo_id}


@app.put("/admin/usuarios/{id_}", tags=["Admin - Usuários"])
def admin_atualizar_usuario(id_: int, payload: UsuarioUpdateIn, usuario: dict = Depends(exigir_admin)):
    if payload.senha and len(payload.senha) < 4:
        raise HTTPException(status_code=422, detail="A senha precisa ter pelo menos 4 caracteres.")
    alvo = db.buscar_usuario_por_id(id_)
    if not alvo:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    # Impede remover o papel de admin (ou desativar) do último administrador
    # ativo — senão o sistema fica sem ninguém que consiga gerenciar usuários.
    deixa_de_ser_admin_ativo = (
        alvo["role"] == "admin" and alvo["ativo"] and (payload.role != "admin" or not payload.ativo)
    )
    if deixa_de_ser_admin_ativo and db.contar_admins_ativos(ignorar_id=id_) == 0:
        raise HTTPException(
            status_code=422, detail="Não é possível remover o último administrador ativo do sistema.",
        )
    try:
        db.atualizar_usuario(id_, nome=payload.nome, username=payload.username, role=payload.role, ativo=payload.ativo)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail=f"Já existe um usuário com o login '{payload.username}'.")
    if payload.senha:
        senha_hash, senha_salt = auth.gerar_hash_senha(payload.senha)
        db.atualizar_senha_usuario(id_, senha_hash, senha_salt)
    return {"status": "ok"}


@app.delete("/admin/usuarios/{id_}", tags=["Admin - Usuários"])
def admin_excluir_usuario(id_: int, usuario: dict = Depends(exigir_admin)):
    if id_ == usuario["id"]:
        raise HTTPException(status_code=422, detail="Não é possível excluir o próprio usuário logado.")
    alvo = db.buscar_usuario_por_id(id_)
    if not alvo:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    if alvo["role"] == "admin" and alvo["ativo"] and db.contar_admins_ativos(ignorar_id=id_) == 0:
        raise HTTPException(status_code=422, detail="Não é possível excluir o último administrador ativo do sistema.")
    db.excluir_usuario(id_)
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)