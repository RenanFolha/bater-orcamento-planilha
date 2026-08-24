"""Rotas de autenticação: login, logout, usuário logado e troca de senha."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response

import auth_service as auth
import frete_db as db
from deps import COOKIE_SESSAO, exigir_login
from schemas import LoginRequest, TrocarSenhaRequest

router = APIRouter(prefix="/auth", tags=["Autenticação"])


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response):
    ip = request.client.host if request.client else "desconhecido"
    # Bloqueio por IP *e* por username: só por IP não protege usuários
    # atrás do mesmo NAT/proxy corporativo entre si, e só por username
    # permitiria um atacante testar senhas de contas diferentes sem
    # nunca bater o limite. As duas chaves são independentes (contadores
    # próprios), então usar uma identidade não "gasta" o limite da outra.
    chave_usuario = f"user:{payload.username.strip().lower()}"
    espera = max(auth.login_bloqueado(ip), auth.login_bloqueado(chave_usuario))
    if espera:
        raise HTTPException(
            status_code=429,
            detail=f"Muitas tentativas de login falhas. Tente novamente em {espera // 60 + 1} minuto(s).",
            headers={"Retry-After": str(espera)},
        )

    usuario = auth.autenticar(payload.username, payload.senha)
    if not usuario:
        auth.registrar_tentativa_falha(ip)
        auth.registrar_tentativa_falha(chave_usuario)
        raise HTTPException(status_code=401, detail="Usuário ou senha inválidos.")
    auth.limpar_tentativas_falha(ip)
    auth.limpar_tentativas_falha(chave_usuario)
    token = auth.criar_sessao(usuario["id"])
    response.set_cookie(
        COOKIE_SESSAO, token, httponly=True, samesite="lax",
        max_age=auth.SESSAO_DURACAO_HORAS * 3600, path="/",
    )
    return {"id": usuario["id"], "nome": usuario["nome"], "username": usuario["username"], "role": usuario["role"]}


@router.post("/logout")
def logout(request: Request, response: Response):
    auth.encerrar_sessao(request.cookies.get(COOKIE_SESSAO))
    response.delete_cookie(COOKIE_SESSAO, path="/")
    return {"status": "ok"}


@router.get("/me")
def me(usuario: dict = Depends(exigir_login)):
    return usuario


@router.post("/trocar-senha")
def trocar_senha(payload: TrocarSenhaRequest, usuario: dict = Depends(exigir_login)):
    if not auth.autenticar(usuario["username"], payload.senha_atual):
        raise HTTPException(status_code=401, detail="Senha atual incorreta.")
    senha_hash, senha_salt = auth.gerar_hash_senha(payload.senha_nova)
    db.atualizar_senha_usuario(usuario["id"], senha_hash, senha_salt)
    return {"status": "ok"}
