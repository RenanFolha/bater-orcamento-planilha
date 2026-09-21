# Desenvolvedor Chefe: RenanFolha

"""Rota de cálculo de orçamento Fracionado — pública, não exige login.
Mesmo padrão de routers/orcamento.py, mas chama
frete_service.calcular_orcamento_fracionado (frete base por faixa de
peso + distância, em vez de veículo escolhido pelo peso)."""

from fastapi import APIRouter, HTTPException

import frete_service as fs
from schemas import OrcamentoFracionadoRequest

router = APIRouter(tags=["Orçamento Fracionado"])


@router.post("/orcamento/fracionado")
def orcamento_fracionado(payload: OrcamentoFracionadoRequest):
    try:
        return fs.calcular_orcamento_fracionado(
            peso=payload.peso,
            paletes=[p.model_dump() for p in payload.paletes],
            distancia=payload.distancia,
            valor_mercadoria=payload.valor_mercadoria,
            categoria=payload.categoria,
            transporte=payload.transporte,
            sla=payload.sla,
            veiculo=payload.veiculo,
            cidade_origem=payload.cidade_origem or None,
            cidade_destino=payload.cidade_destino or None,
            pedagio=payload.pedagio,
            prioridade_rota=payload.prioridade_rota or None,
            custos_extras=[c.model_dump() for c in payload.custos_extras],
        )
    except fs.FreteInputError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except fs.FreteConfigError as e:
        raise HTTPException(status_code=500, detail=f"Erro de configuração: {e}") from e
