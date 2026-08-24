"""Rotas de geolocalização: distância entre endereços e filial mais próxima."""

from fastapi import APIRouter, HTTPException

import frete_service as fs
import geo_service as geo
from schemas import DistanciaRequest, EntregaRequest, RetiradaRequest, RetornoRequest

router = APIRouter(prefix="/geo", tags=["Geolocalização"])


@router.post("/distancia")
async def distancia_por_endereco(payload: DistanciaRequest):
    """Geocodifica os dois endereços (ou endereços de filiais) e calcula a
    distância rodoviária entre eles (em km). Usado para o trecho principal
    do frete (origem efetiva → destino)."""
    try:
        return await geo.calcular_distancia(payload.origem, payload.destino)
    except geo.GeoError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/resolver-retirada")
async def resolver_retirada(payload: RetiradaRequest):
    """Dado um endereço de retirada no cliente, encontra a filial cadastrada
    mais próxima e calcula a distância de coleta (filial → endereço)."""
    try:
        filiais = list(fs.parametros.filiais.values())
        return await geo.resolver_retirada(payload.endereco_retirada, filiais)
    except geo.GeoError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/resolver-entrega")
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


@router.post("/resolver-retorno")
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
