# Desenvolvedor Chefe: RenanFolha

"""Rotas de geolocalização: distância entre endereços e filial mais próxima."""

from fastapi import APIRouter, Depends, HTTPException, Request

import auth_service as auth
import frete_service as fs
import geo_service as geo
from schemas import DistanciaRequest, EntregaRequest, RetiradaRequest, RetornoRequest

# Limite de chamadas por IP -- essas rotas são públicas e cada uma dispara
# uma requisição de verdade pro serviço de geolocalização (Nominatim/OSRM
# ou Google Maps, se configurado); sem isso, nada impede um script em loop
# de gerar custo real ou estourar a política de uso do provedor externo
# (ver auth_service.limite_generico_excedido).
_GEO_RATE_LIMITE_MAX = 30
_GEO_RATE_LIMITE_JANELA_SEGUNDOS = 60


def _limitar_taxa_geo(request: Request):
    ip = request.client.host if request.client else "desconhecido"
    espera = auth.limite_generico_excedido(
        f"geo:{ip}", maximo=_GEO_RATE_LIMITE_MAX, janela_segundos=_GEO_RATE_LIMITE_JANELA_SEGUNDOS,
    )
    if espera:
        raise HTTPException(
            status_code=429,
            detail=f"Muitas requisições de geolocalização. Tente novamente em {espera} segundo(s).",
            headers={"Retry-After": str(espera)},
        )


router = APIRouter(prefix="/geo", tags=["Geolocalização"], dependencies=[Depends(_limitar_taxa_geo)])


@router.post("/distancia")
async def distancia_por_endereco(payload: DistanciaRequest):
    """Geocodifica os dois endereços (ou endereços de filiais) e calcula a
    distância rodoviária entre eles (em km). Usado para o trecho principal
    do frete (origem efetiva → destino).

    peso/paletes/transporte são opcionais: quando informados, descobrem o
    veículo que o orçamento vai escolher (mesma lógica de
    calcular_orcamento) só pra permitir reaproveitar a distância de uma
    rota+veículo já cotada e salva no histórico, sem precisar geocodificar
    de novo — não fazem parte do cálculo de frete em si."""
    # Um veículo já conhecido (ex: o veículo de referência escolhido no
    # orçamento Fracionado) tem prioridade sobre a inferência por peso —
    # não faz sentido tentar "descobrir" um veículo que a pessoa já
    # informou direto.
    veiculo_nome = payload.veiculo.strip() or None
    if not veiculo_nome and payload.peso > 0 and payload.paletes and payload.transporte:
        try:
            transp = fs.parametros.buscar_transporte(payload.transporte)
            selecao = fs.escolher_veiculo(payload.peso, [p.model_dump() for p in payload.paletes], transp)
            veiculo_nome = selecao.veiculo.nome
        except (fs.FreteInputError, fs.FreteConfigError):
            veiculo_nome = None  # não dá pra descobrir o veículo -> só não reaproveita do histórico

    try:
        return await geo.calcular_distancia(payload.origem, payload.destino, veiculo=veiculo_nome)
    except geo.GeoError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


async def _resolver_filial_mais_proxima(endereco: str):
    """Encontra a filial cadastrada mais próxima de um endereço e a
    distância até ela — mecanismo comum a retirada, entrega e retorno
    vazio (só muda qual endereço é resolvido em cada rota)."""
    try:
        filiais = list(fs.parametros.filiais.values())
        return await geo.resolver_retirada(endereco, filiais)
    except geo.GeoError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.post("/resolver-retirada")
async def resolver_retirada(payload: RetiradaRequest):
    """Dado um endereço de retirada no cliente, encontra a filial cadastrada
    mais próxima e calcula a distância de coleta (filial → endereço)."""
    return await _resolver_filial_mais_proxima(payload.endereco_retirada)


@router.post("/resolver-entrega")
async def resolver_entrega(payload: EntregaRequest):
    """Dado um endereço de entrega no cliente, encontra a filial cadastrada
    mais próxima. Usado quando a entrega final é terceirizada: a rota
    principal (frota própria) vai só até essa filial, e o trecho
    filial → cliente fica por conta da transportadora contratada."""
    return await _resolver_filial_mais_proxima(payload.endereco_entrega)


@router.post("/resolver-retorno")
async def resolver_retorno(payload: RetornoRequest):
    """Dado o endereço final da entrega, encontra a filial cadastrada mais
    próxima pra onde o veículo (vazio) precisa voltar depois de entregar —
    usado pra estimar o custo do retorno vazio. Sempre precisa ser
    confirmado na tela antes de entrar no orçamento, porque o veículo
    pode não voltar exatamente pra filial mais próxima geograficamente."""
    return await _resolver_filial_mais_proxima(payload.endereco_destino)
