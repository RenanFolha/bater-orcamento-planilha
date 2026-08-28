"""Rota de cálculo de orçamento — pública, não exige login."""

from fastapi import APIRouter, HTTPException

import frete_service as fs
from schemas import OrcamentoRequest

router = APIRouter(tags=["Orçamento"])


@router.post("/orcamento")
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
        raise HTTPException(status_code=422, detail=str(e)) from e
    except fs.FreteConfigError as e:
        raise HTTPException(status_code=500, detail=f"Erro de configuração: {e}") from e
