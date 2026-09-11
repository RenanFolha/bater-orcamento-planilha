# Desenvolvedor Chefe: RenanFolha

"""Rotas do histórico de orçamentos salvos — todas exigem login."""

import json

from fastapi import APIRouter, Depends, HTTPException, Response

import export_service as export
import frete_db as db
from deps import exigir_login
from schemas import AtualizarPedagioHistoricoRequest, HistoricoSalvarRequest

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
    GET /historico/{codigo} pra ver os detalhes de um orçamento específico.

    Usuário comum só vê os próprios orçamentos (criado_por == username);
    administrador vê todos — evita que qualquer conta logada enxergue
    cliente/endereço/valor de orçamentos de outras pessoas da empresa
    (minimização de dados, LGPD)."""
    registros = db.listar_orcamentos_historico()
    for r in registros:
        r.pop("dados_json", None)
    if usuario["role"] != "admin":
        registros = [r for r in registros if (r.get("criado_por") or "") == usuario["username"]]
    return registros


def _buscar_historico_com_dados(codigo: str) -> dict:
    """Busca o registro do histórico por código e já desserializa o
    snapshot completo do orçamento (dados_json) — usado tanto pra exibir
    o detalhe quanto pra gerar a planilha exportada."""
    registro = db.buscar_orcamento_historico(codigo)
    if not registro:
        raise HTTPException(status_code=404, detail=f"Orçamento '{codigo}' não encontrado no histórico.")
    registro["dados"] = json.loads(registro.pop("dados_json") or "{}")
    registro["alteracoes"] = db.listar_alteracoes_historico(registro["id"])
    return registro


@router.get("/{codigo}")
def obter_historico(codigo: str, usuario: dict = Depends(exigir_login)):
    registro = _buscar_historico_com_dados(codigo)
    _exigir_dono_ou_admin(registro, usuario, "ver")
    return registro


def _exigir_dono_ou_admin(registro: dict, usuario: dict, acao: str) -> None:
    """Só quem salvou o registro (mesma conta logada) ou um administrador
    pode ver/excluir/editar — registros de bancos antigos (sem criado_por
    preenchido) só ficam acessíveis a um admin."""
    dono = registro.get("criado_por") or ""
    if usuario["role"] != "admin" and dono != usuario["username"]:
        raise HTTPException(
            status_code=403,
            detail=f"Só o administrador ou quem salvou este orçamento pode {acao}.",
        )


@router.delete("/{id_}")
def excluir_historico(id_: int, usuario: dict = Depends(exigir_login)):
    registro = db.buscar_orcamento_historico_por_id(id_)
    if not registro:
        raise HTTPException(status_code=404, detail="Orçamento não encontrado no histórico.")
    _exigir_dono_ou_admin(registro, usuario, "excluí-lo")
    db.excluir_orcamento_historico(id_)
    return {"status": "ok"}


@router.put("/{id_}/pedagio")
def atualizar_pedagio(id_: int, payload: AtualizarPedagioHistoricoRequest, usuario: dict = Depends(exigir_login)):
    """Corrige o valor do pedágio de um orçamento já salvo (ex: o valor
    estimado pelo Google Maps na hora da cotação estava errado). Recalcula
    o frete total só pela diferença entre o pedágio antigo e o novo — o
    resto do orçamento continua refletindo os parâmetros de quando foi
    cotado, não a tabela de preços atual."""
    registro = db.buscar_orcamento_historico_por_id(id_)
    if not registro:
        raise HTTPException(status_code=404, detail="Orçamento não encontrado no histórico.")
    _exigir_dono_ou_admin(registro, usuario, "editá-lo")

    dados = json.loads(registro["dados_json"] or "{}")
    resultado = dados.setdefault("resultado", {})
    calc = resultado.setdefault("calculos_intermediarios", {})
    pedagio_antigo = calc.get("pedagio") or 0
    novo_pedagio = round(payload.pedagio, 2)
    calc["pedagio"] = novo_pedagio

    res_final = resultado.setdefault("resultado", {})
    frete_total_antigo = res_final.get("frete_total", registro["frete_total"]) or 0
    frete_total_novo = round(frete_total_antigo - pedagio_antigo + novo_pedagio, 2)
    res_final["frete_total"] = frete_total_novo

    if isinstance(dados.get("payload"), dict):
        dados["payload"]["pedagio"] = novo_pedagio

    db.atualizar_pedagio_historico(
        id_, frete_total_novo, json.dumps(dados, ensure_ascii=False),
        pedagio_antigo=pedagio_antigo, pedagio_novo=novo_pedagio, alterado_por=usuario["username"],
    )
    return {"status": "ok", "pedagio": novo_pedagio, "frete_total": frete_total_novo}


@router.get("/{codigo}/planilha")
def exportar_historico_planilha(codigo: str, usuario: dict = Depends(exigir_login)):
    """Gera a planilha de orçamento (formato 'Modelo de Orçamento.xlsx')
    preenchida com os dados desse orçamento do histórico."""
    registro = _buscar_historico_com_dados(codigo)
    _exigir_dono_ou_admin(registro, usuario, "exportá-lo")
    try:
        conteudo = export.gerar_planilha_orcamento(registro)
    except export.ExportacaoError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return Response(
        content=conteudo,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="Orcamento_{codigo}.xlsx"'},
    )
