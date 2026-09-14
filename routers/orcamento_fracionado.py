# Desenvolvedor Chefe: RenanFolha

"""Rota de cálculo de orçamento Fracionado — pública, não exige login.
Mesmo padrão de routers/orcamento.py, mas chama
frete_service.calcular_orcamento_fracionado (frete base por faixa de
peso + distância, em vez de veículo escolhido pelo peso)."""

from fastapi import APIRouter, Depends, HTTPException

import frete_service as fs
from deps import usuario_atual
from schemas import OrcamentoFracionadoRequest

router = APIRouter(tags=["Orçamento Fracionado"])


@router.post("/orcamento/fracionado")
def orcamento_fracionado(payload: OrcamentoFracionadoRequest, usuario: dict | None = Depends(usuario_atual)):
    # Mesma restrição de margem abaixo de 40% do orçamento normal (ver
    # routers/orcamento.py) — restrita a administradores.
    if payload.margem_lucro_pct < fs.MARGEM_LUCRO_MINIMA_SEM_ADMIN and not (usuario and usuario["role"] == "admin"):
        raise HTTPException(
            status_code=403,
            detail=f"Margem de lucro abaixo de {fs.MARGEM_LUCRO_MINIMA_SEM_ADMIN}% é restrita a administradores.",
        )
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
            margem_lucro_pct=payload.margem_lucro_pct,
        )
    except fs.FreteInputError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except fs.FreteConfigError as e:
        raise HTTPException(status_code=500, detail=f"Erro de configuração: {e}") from e
