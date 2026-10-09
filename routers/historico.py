# Desenvolvedor Chefe: RenanFolha

"""Rotas do histórico de orçamentos salvos — todas exigem login."""

import json

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import ValidationError

import export_service as export
import frete_db as db
import frete_service as fs
from deps import exigir_login
from routers.orcamento import montar_resultado as montar_resultado_veiculo_por_peso
from routers.orcamento_fracionado import montar_resultado as montar_resultado_fracionado
from schemas import (
    AtualizarPedagioHistoricoRequest,
    HistoricoSalvarRequest,
    OrcamentoFracionadoRequest,
    OrcamentoRequest,
)

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
    o detalhe quanto pra gerar o PDF exportado."""
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

    dados_json_esperado = registro["dados_json"]
    dados = json.loads(dados_json_esperado or "{}")
    resultado = dados.setdefault("resultado", {})
    calc = resultado.setdefault("calculos_intermediarios", {})
    pedagio_antigo = calc.get("pedagio") or 0
    novo_pedagio = round(payload.pedagio, 2)
    calc["pedagio"] = novo_pedagio

    res_final = resultado.setdefault("resultado", {})
    frete_total_antigo = res_final.get("frete_total", registro["frete_total"]) or 0
    # Piso em 0 -- sem isso, corrigir um pedágio antigo super estimado pra
    # um valor bem menor podia zerar ou até inverter o sinal do frete
    # total salvo (ver achado de revisão de código).
    frete_total_novo = max(0.0, round(frete_total_antigo - pedagio_antigo + novo_pedagio, 2))
    res_final["frete_total"] = frete_total_novo

    if isinstance(dados.get("payload"), dict):
        dados["payload"]["pedagio"] = novo_pedagio

    try:
        db.atualizar_pedagio_historico(
            id_, frete_total_novo, json.dumps(dados, ensure_ascii=False),
            pedagio_antigo=pedagio_antigo, pedagio_novo=novo_pedagio, alterado_por=usuario["username"],
            dados_json_esperado=dados_json_esperado,
        )
    except db.ConflitoIntegridade as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return {"status": "ok", "pedagio": novo_pedagio, "frete_total": frete_total_novo}


@router.put("/{id_}/recalcular")
def recalcular_historico(id_: int, usuario: dict = Depends(exigir_login)):
    """Recalcula um orçamento já salvo com os parâmetros ATUAIS da Tabela
    de Preços (ex: depois de um reajuste que deve valer retroativamente
    pros orçamentos já cotados, como a mudança na fórmula do pedágio) --
    reaplica o payload original salvo (dados.payload) contra
    calcular_orcamento/calcular_orcamento_fracionado (mesma função usada
    por POST /orcamento[/fracionado], ver routers/orcamento.py e
    routers/orcamento_fracionado.py) e sobrescreve frete_total e o
    snapshot inteiro (dados.resultado) -- diferente de PUT /{id}/pedagio,
    que só ajusta o campo pedágio dentro do snapshot sem reprocessar o
    resto. Distingue orçamento normal (veículo escolhido pelo peso) de
    Fracionado pela presença do campo "veiculo" no payload salvo -- só
    existe no Fracionado (ver schemas.OrcamentoFracionadoRequest)."""
    registro = db.buscar_orcamento_historico_por_id(id_)
    if not registro:
        raise HTTPException(status_code=404, detail="Orçamento não encontrado no histórico.")
    _exigir_dono_ou_admin(registro, usuario, "recalculá-lo")

    dados_json_esperado = registro["dados_json"]
    dados = json.loads(dados_json_esperado or "{}")
    payload_salvo = dados.get("payload")
    if not isinstance(payload_salvo, dict):
        raise HTTPException(
            status_code=422,
            detail="Esse orçamento não tem os dados originais da cotação salvos (registro antigo) "
                   "-- não é possível recalcular automaticamente.",
        )
    # Registros antigos podem ter campos opcionais salvos como null (ex:
    # prioridade_rota antes de um fallback pra string vazia existir no
    # front) -- o schema atual não aceita None nesses campos. Remove
    # antes de validar pra cair no valor padrão do campo, em vez de 422
    # por um detalhe de como o front salvou naquela época.
    payload_salvo = {k: v for k, v in payload_salvo.items() if v is not None}

    try:
        if "veiculo" in payload_salvo:
            resultado = montar_resultado_fracionado(OrcamentoFracionadoRequest(**payload_salvo))
        else:
            resultado = montar_resultado_veiculo_por_peso(OrcamentoRequest(**payload_salvo))
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=f"Dados originais da cotação inválidos: {e}") from e
    except fs.FreteInputError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except fs.FreteConfigError as e:
        raise HTTPException(status_code=500, detail=f"Erro de configuração: {e}") from e

    frete_total_antigo = registro["frete_total"]
    frete_total_novo = resultado["resultado"]["frete_total"]
    dados["resultado"] = resultado

    try:
        db.atualizar_recalculo_historico(
            id_, frete_total_novo, json.dumps(dados, ensure_ascii=False),
            frete_total_antigo=frete_total_antigo, alterado_por=usuario["username"],
            dados_json_esperado=dados_json_esperado,
        )
    except db.ConflitoIntegridade as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return {"status": "ok", "frete_total_antigo": frete_total_antigo, "frete_total": frete_total_novo}


@router.get("/{codigo}/pdf")
def exportar_historico_pdf(codigo: str, usuario: dict = Depends(exigir_login)):
    """Gera o PDF de cotação (Modelo 1 -- cotação única, estilo proposta
    comercial) preenchido com os dados desse orçamento do histórico."""
    registro = _buscar_historico_com_dados(codigo)
    _exigir_dono_ou_admin(registro, usuario, "exportá-lo")
    try:
        conteudo = export.gerar_pdf_orcamento(registro)
    except export.ExportacaoError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return Response(
        content=conteudo,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="Orcamento_{codigo}.pdf"'},
    )
