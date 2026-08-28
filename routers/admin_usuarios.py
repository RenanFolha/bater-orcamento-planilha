"""CRUD administrativo de usuários — só administrador."""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

import auth_service as auth
import frete_db as db
from deps import exigir_admin
from schemas import SENHA_MIN_LENGTH, UsuarioIn, UsuarioUpdateIn

router = APIRouter(prefix="/admin/usuarios", tags=["Admin - Usuários"])


@router.get("")
def admin_listar_usuarios(usuario: dict = Depends(exigir_admin)):
    return db.listar_usuarios_admin()


@router.post("")
def admin_criar_usuario(payload: UsuarioIn, usuario: dict = Depends(exigir_admin)):
    senha_hash, senha_salt = auth.gerar_hash_senha(payload.senha)
    try:
        novo_id = db.inserir_usuario(
            nome=payload.nome, username=payload.username,
            senha_hash=senha_hash, senha_salt=senha_salt,
            role=payload.role, ativo=payload.ativo,
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail=f"Já existe um usuário com o login '{payload.username}'.") from exc
    return {"id": novo_id}


@router.put("/{id_}")
def admin_atualizar_usuario(id_: int, payload: UsuarioUpdateIn, usuario: dict = Depends(exigir_admin)):
    if payload.senha and len(payload.senha) < SENHA_MIN_LENGTH:
        raise HTTPException(status_code=422, detail=f"A senha precisa ter pelo menos {SENHA_MIN_LENGTH} caracteres.")
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
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail=f"Já existe um usuário com o login '{payload.username}'.") from exc
    if payload.senha:
        senha_hash, senha_salt = auth.gerar_hash_senha(payload.senha)
        db.atualizar_senha_usuario(id_, senha_hash, senha_salt)
    return {"status": "ok"}


@router.delete("/{id_}")
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
