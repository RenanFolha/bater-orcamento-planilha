# Desenvolvedor Chefe: RenanFolha

"""
Testes de auth_service.py: hash/verificação de senha, bloqueio de login
por tentativas falhas e ciclo de vida da sessão (criar/validar/expirar).
Usam o fixture `banco_temporario` (ver conftest.py) — nada aqui toca no
frete.db real.
"""


import auth_service as auth
import frete_db as db


def test_hash_senha_gera_valores_diferentes_por_salt():
    hash1, salt1 = auth.gerar_hash_senha("minhasenha123")
    hash2, salt2 = auth.gerar_hash_senha("minhasenha123")
    assert salt1 != salt2
    assert hash1 != hash2  # salts diferentes -> hashes diferentes mesmo pra mesma senha


def test_verificar_senha_correta_e_incorreta():
    senha_hash, senha_salt = auth.gerar_hash_senha("correta123")
    assert auth.verificar_senha("correta123", senha_hash, senha_salt) is True
    assert auth.verificar_senha("errada456", senha_hash, senha_salt) is False


def test_garantir_usuario_padrao_so_cria_se_banco_vazio(banco_temporario):
    auth.garantir_usuario_padrao()
    assert db.contar_usuarios() == 1
    admin = db.buscar_usuario_por_username(auth.ADMIN_USERNAME_PADRAO)
    assert admin["role"] == "admin"

    # rodar de novo não deve duplicar o admin padrão
    auth.garantir_usuario_padrao()
    assert db.contar_usuarios() == 1


def test_autenticar_fluxo_completo(banco_temporario):
    auth.garantir_usuario_padrao()
    assert auth.autenticar(auth.ADMIN_USERNAME_PADRAO, auth.ADMIN_SENHA_PADRAO) is not None
    assert auth.autenticar(auth.ADMIN_USERNAME_PADRAO, "senha-errada") is None
    assert auth.autenticar("usuario-inexistente", "qualquer") is None


def test_autenticar_usuario_inativo_falha(banco_temporario):
    senha_hash, senha_salt = auth.gerar_hash_senha("123456ab")
    db.inserir_usuario(
        nome="Inativo", username="inativo", senha_hash=senha_hash,
        senha_salt=senha_salt, role="usuario", ativo=False,
    )
    assert auth.autenticar("inativo", "123456ab") is None


def test_login_bloqueado_apos_exceder_tentativas():
    identificador = "teste-ip-1"
    for _ in range(auth._LOGIN_MAX_TENTATIVAS):
        assert auth.login_bloqueado(identificador) == 0
        auth.registrar_tentativa_falha(identificador)
    # a tentativa seguinte já deveria estar bloqueada
    assert auth.login_bloqueado(identificador) > 0


def test_limpar_tentativas_falha_libera_o_bloqueio():
    identificador = "teste-ip-2"
    for _ in range(auth._LOGIN_MAX_TENTATIVAS):
        auth.registrar_tentativa_falha(identificador)
    assert auth.login_bloqueado(identificador) > 0
    auth.limpar_tentativas_falha(identificador)
    assert auth.login_bloqueado(identificador) == 0


def test_sessao_criada_e_validada(banco_temporario):
    auth.garantir_usuario_padrao()
    admin = db.buscar_usuario_por_username(auth.ADMIN_USERNAME_PADRAO)
    token = auth.criar_sessao(admin["id"])
    sessao = auth.validar_sessao(token)
    assert sessao is not None
    assert sessao["username"] == auth.ADMIN_USERNAME_PADRAO


def test_sessao_invalida_ou_ausente(banco_temporario):
    assert auth.validar_sessao(None) is None
    assert auth.validar_sessao("token-que-nao-existe") is None


def test_sessao_expirada_e_removida_do_banco(banco_temporario):
    usuario_id = db.inserir_usuario(
        nome="Teste", username="teste-sessao", senha_hash="x", senha_salt="y",
        role="usuario", ativo=True,
    )
    passado = "2000-01-01T00:00:00"
    db.criar_sessao("token-expirado", usuario_id, passado, passado)
    assert auth.validar_sessao("token-expirado") is None
    # validar_sessao deve ter limpado a sessão expirada do banco
    assert db.buscar_sessao("token-expirado") is None


def test_sessao_de_usuario_desativado_apos_a_sessao_criada_e_invalidada(banco_temporario):
    # A sessão em si continua válida (não expirou) mas o usuário foi
    # desativado depois de já ter logado -- validar_sessao precisa
    # recusar mesmo assim, não só checar a validade do token isolado.
    usuario_id = db.inserir_usuario(
        nome="Teste", username="teste-inativo", senha_hash="x", senha_salt="y",
        role="usuario", ativo=True,
    )
    token = auth.criar_sessao(usuario_id)
    with db.get_connection() as conn:
        conn.execute("UPDATE usuarios SET ativo=0 WHERE id=?", (usuario_id,))
    assert auth.validar_sessao(token) is None


def test_encerrar_sessao_remove_token(banco_temporario):
    auth.garantir_usuario_padrao()
    admin = db.buscar_usuario_por_username(auth.ADMIN_USERNAME_PADRAO)
    token = auth.criar_sessao(admin["id"])
    auth.encerrar_sessao(token)
    assert auth.validar_sessao(token) is None


def test_marca_admin_padrao_pendente_quando_banco_antigo_nao_tinha_o_sinalizador(banco_temporario):
    # simula um banco criado antes de existir a coluna deve_trocar_senha
    # (ver frete_db._migrar_colunas): admin com a senha padrão, mas sem o
    # sinalizador marcado -- garantir_usuario_padrao (chamada de novo, como
    # se a API tivesse reiniciado) precisa detectar e marcar a pendência.
    auth.garantir_usuario_padrao()
    admin = db.buscar_usuario_por_username(auth.ADMIN_USERNAME_PADRAO)
    with db.get_connection() as conn:
        conn.execute("UPDATE usuarios SET deve_trocar_senha=0 WHERE id=?", (admin["id"],))

    auth.garantir_usuario_padrao()  # contar_usuarios() > 0 -> cai no ramo de marcar pendência

    admin_depois = db.buscar_usuario_por_username(auth.ADMIN_USERNAME_PADRAO)
    assert admin_depois["deve_trocar_senha"] == 1


def test_nao_marca_pendente_quando_senha_ja_foi_trocada(banco_temporario):
    auth.garantir_usuario_padrao()
    admin = db.buscar_usuario_por_username(auth.ADMIN_USERNAME_PADRAO)
    senha_hash, senha_salt = auth.gerar_hash_senha("outra-senha-diferente")
    db.atualizar_senha_usuario(admin["id"], senha_hash, senha_salt)  # já limpa deve_trocar_senha

    auth.garantir_usuario_padrao()

    admin_depois = db.buscar_usuario_por_username(auth.ADMIN_USERNAME_PADRAO)
    assert admin_depois["deve_trocar_senha"] == 0
