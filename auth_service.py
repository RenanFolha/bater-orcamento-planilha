# Desenvolvedor Chefe: RenanFolha

"""
Login e controle de sessão.

Senhas são guardadas como hash PBKDF2-HMAC-SHA256 (biblioteca padrão do
Python, sem dependência extra) + salt aleatório por usuário — nunca em
texto puro. A sessão é um token aleatório gravado na tabela `sessoes`
do banco e devolvido ao navegador num cookie httponly; a cada
requisição protegida o servidor confere esse token contra o banco (não
é um JWT autocontido, então revogar/expirar sessão é só apagar a
linha).

Dois papéis: 'admin' (gerencia usuários, Tabela de Preços e
Configurações) e 'usuario' (só gera orçamentos e vê o Histórico — ver
main.py para onde cada papel é exigido).
"""

import hashlib
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta

import frete_db as db

SESSAO_DURACAO_HORAS = 12
_PBKDF2_ITERACOES = 200_000

ADMIN_USERNAME_PADRAO = "admin"
ADMIN_SENHA_PADRAO = "admin123"

# Limite de tentativas de login por IP: protege contra força bruta (ex:
# tentar adivinhar a senha do admin padrão) sem precisar de dependência
# externa nem de banco — é só um contador em memória do processo, então
# reinicia se a API reiniciar (aceitável para o volume de uso deste sistema).
_LOGIN_MAX_TENTATIVAS = 5
_LOGIN_JANELA_SEGUNDOS = 15 * 60
_tentativas_login: dict[str, list[float]] = defaultdict(list)


def _limpar_tentativas_antigas(identificador: str, agora: float):
    limite = agora - _LOGIN_JANELA_SEGUNDOS
    _tentativas_login[identificador] = [t for t in _tentativas_login[identificador] if t > limite]


def login_bloqueado(identificador: str) -> int:
    """Retorna quantos segundos faltam até o identificador (ex: IP) poder
    tentar de novo, ou 0 se não estiver bloqueado."""
    agora = time.monotonic()
    _limpar_tentativas_antigas(identificador, agora)
    tentativas = _tentativas_login[identificador]
    if len(tentativas) < _LOGIN_MAX_TENTATIVAS:
        return 0
    return max(0, round(_LOGIN_JANELA_SEGUNDOS - (agora - tentativas[0])))


def registrar_tentativa_falha(identificador: str):
    _tentativas_login[identificador].append(time.monotonic())


def limpar_tentativas_falha(identificador: str):
    _tentativas_login.pop(identificador, None)


def gerar_hash_senha(senha: str) -> tuple[str, str]:
    salt = secrets.token_hex(16)
    hash_ = hashlib.pbkdf2_hmac(
        "sha256", senha.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ITERACOES
    ).hex()
    return hash_, salt


def verificar_senha(senha: str, senha_hash: str, senha_salt: str) -> bool:
    tentativa = hashlib.pbkdf2_hmac(
        "sha256", senha.encode("utf-8"), bytes.fromhex(senha_salt), _PBKDF2_ITERACOES
    ).hex()
    return secrets.compare_digest(tentativa, senha_hash)


def garantir_usuario_padrao():
    """Na primeira execução (nenhum usuário cadastrado ainda), cria o
    admin padrão para não deixar o sistema sem ninguém que consiga
    entrar. Troque a senha assim que possível (tela de login →
    "Trocar senha")."""
    if db.contar_usuarios() > 0:
        _marcar_admin_padrao_pendente_se_necessario()
        return
    senha_hash, senha_salt = gerar_hash_senha(ADMIN_SENHA_PADRAO)
    db.inserir_usuario(
        nome="Administrador", username=ADMIN_USERNAME_PADRAO,
        senha_hash=senha_hash, senha_salt=senha_salt, role="admin", ativo=True,
        deve_trocar_senha=True,
    )
    print(
        f"[frete] Usuário admin padrão criado — login: '{ADMIN_USERNAME_PADRAO}' / "
        f"senha: '{ADMIN_SENHA_PADRAO}'. Troque a senha assim que possível."
    )


def _marcar_admin_padrao_pendente_se_necessario():
    """Cobre bancos que já existiam antes do sinalizador deve_trocar_senha
    (ver migração em frete_db.py): se o usuário 'admin' ainda estiver com a
    senha padrão 'admin123', marca a troca como pendente — sem isso, quem
    já tinha o frete.db criado ficava sem o aviso de senha padrão."""
    usuario = db.buscar_usuario_por_username(ADMIN_USERNAME_PADRAO)
    if not usuario or usuario["deve_trocar_senha"]:
        return
    if verificar_senha(ADMIN_SENHA_PADRAO, usuario["senha_hash"], usuario["senha_salt"]):
        db.marcar_deve_trocar_senha(usuario["id"])


def autenticar(username: str, senha: str) -> dict | None:
    usuario = db.buscar_usuario_por_username(username)
    if not usuario or not usuario["ativo"]:
        return None
    if not verificar_senha(senha, usuario["senha_hash"], usuario["senha_salt"]):
        return None
    return usuario


def criar_sessao(usuario_id: int) -> str:
    token = secrets.token_urlsafe(32)
    agora = datetime.now()
    expira = agora + timedelta(hours=SESSAO_DURACAO_HORAS)
    db.limpar_sessoes_expiradas(agora.isoformat(timespec="seconds"))
    db.criar_sessao(token, usuario_id, agora.isoformat(timespec="seconds"), expira.isoformat(timespec="seconds"))
    return token


def validar_sessao(token: str | None) -> dict | None:
    if not token:
        return None
    sessao = db.buscar_sessao(token)
    if not sessao:
        return None
    if sessao["expira_em"] < datetime.now().isoformat(timespec="seconds"):
        db.excluir_sessao(token)
        return None
    if not sessao["ativo"]:
        return None
    return {
        "id": sessao["id"], "nome": sessao["nome"], "username": sessao["username"], "role": sessao["role"],
        "deve_trocar_senha": bool(sessao["deve_trocar_senha"]),
    }


def encerrar_sessao(token: str | None):
    if token:
        db.excluir_sessao(token)
