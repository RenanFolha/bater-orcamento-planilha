"""Rotas do histórico de orçamentos salvos — todas exigem login."""

import json

from fastapi import APIRouter, Depends, HTTPException, Response

import export_service as export
import frete_db as db
from deps import exigir_login
from schemas import HistoricoSalvarRequest

router = APIRouter(prefix="/historico", tags=["Histórico"])


@router.post("")
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
        # "responsavel" acima é texto livre digitado pelo usuário (pode ser
        # o nome de outro colega, não necessariamente quem está logado).
        # "criado_por" é a conta autenticada que de fato salvou o registro —
        # usado só para decidir quem pode excluir (ver DELETE abaixo).
        criado_por=usuario["username"],
    )
    return info


@router.get("")
def listar_historico(usuario: dict = Depends(exigir_login)):
    """Lista o histórico sem o snapshot completo (fica pesado) — use
    GET /historico/{codigo} pra ver os detalhes de um orçamento específico."""
    registros = db.listar_orcamentos_historico()
    for r in registros:
        r.pop("dados_json", None)
    return registros


@router.get("/{codigo}")
def obter_historico(codigo: str, usuario: dict = Depends(exigir_login)):
    registro = db.buscar_orcamento_historico(codigo)
    if not registro:
        raise HTTPException(status_code=404, detail=f"Orçamento '{codigo}' não encontrado no histórico.")
    registro["dados"] = json.loads(registro.pop("dados_json") or "{}")
    return registro


@router.delete("/{id_}")
def excluir_historico(id_: int, usuario: dict = Depends(exigir_login)):
    registro = db.buscar_orcamento_historico_por_id(id_)
    if not registro:
        raise HTTPException(status_code=404, detail="Orçamento não encontrado no histórico.")
    # Só quem salvou o registro (mesma conta logada) ou um administrador
    # pode excluir — antes, qualquer usuário logado podia apagar o
    # histórico de qualquer outro. Registros de bancos antigos (sem
    # criado_por preenchido) só saem pela mão de um admin.
    dono = registro.get("criado_por") or ""
    if usuario["role"] != "admin" and dono != usuario["username"]:
        raise HTTPException(
            status_code=403,
            detail="Só o administrador ou quem salvou este orçamento pode excluí-lo.",
        )
    db.excluir_orcamento_historico(id_)
    return {"status": "ok"}


@router.get("/{codigo}/planilha")
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
        raise HTTPException(status_code=500, detail=str(e)) from e
    return Response(
        content=conteudo,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="Orcamento_{codigo}.xlsx"'},
    )
