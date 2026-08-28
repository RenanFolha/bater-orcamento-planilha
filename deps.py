"""
Dependências compartilhadas pelas rotas: usuário logado a partir do cookie
de sessão, e os helpers genéricos de criar/atualizar/excluir usados pelos
endpoints CRUD de /admin/* (ver routers/admin_precos.py).
"""

import sqlite3

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel

import auth_service as auth
import frete_service as fs

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


# ============================================================
# CRUD da tela "Tabela de Preços" — cada escrita recarrega o cache
# de parâmetros em memória, então o cálculo de frete já reflete a
# mudança na hora, sem precisar chamar /admin/reload manualmente.
#
# Os handlers (ver routers/admin_precos.py) delegam para estas três
# funções: cada rota continua explícita (uma função por tabela, sem
# despachar por nome de tabela vindo do payload) para manter o schema
# do OpenAPI e evitar SQL dinâmico a partir de entrada do usuário —
# só o try/except de conflito e o reload pós-escrita, que eram
# idênticos em ~40 handlers, foram centralizados aqui.
# ============================================================


def admin_criar(inserir_fn, payload: BaseModel, msg_conflito: str, reload: bool = True) -> dict:
    try:
        novo_id = inserir_fn(**payload.model_dump())
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail=msg_conflito) from exc
    if reload:
        fs.carregar_parametros()
    return {"id": novo_id}


def admin_atualizar(atualizar_fn, id_: int, payload: BaseModel, msg_conflito: str, reload: bool = True) -> dict:
    try:
        atualizar_fn(id_, **payload.model_dump())
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail=msg_conflito) from exc
    if reload:
        fs.carregar_parametros()
    return {"status": "ok"}


def admin_excluir(excluir_fn, id_: int, contar_fn=None, msg_ultimo: str = "", reload: bool = True) -> dict:
    if contar_fn is not None and contar_fn() <= 1:
        raise HTTPException(status_code=422, detail=msg_ultimo)
    excluir_fn(id_)
    if reload:
        fs.carregar_parametros()
    return {"status": "ok"}
