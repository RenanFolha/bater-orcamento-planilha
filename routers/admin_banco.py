# Desenvolvedor Chefe: RenanFolha

"""Configuração de qual banco de dados a API usa (SQLite local, ou um
servidor SQL Server/MySQL/PostgreSQL externo) — tela Configurações →
"Banco de dados". Só administrador (ver deps.exigir_admin).

Este ambiente de desenvolvimento não tem SQL Server/MySQL/PostgreSQL
instalados: a sintaxe de cada dialeto (ver frete_db._gerar_schema_consolidado
e db_conexao.conectar) foi escrita com base no padrão documentado de
cada um, mas só foi validada de fato contra SQLite — "Testar conexão"
é o jeito de confirmar que bate certinho com um servidor real antes de
migrar os dados de verdade."""

from fastapi import APIRouter, Depends, HTTPException

import db_conexao
import frete_db as db
import frete_service as fs
from deps import exigir_admin
from schemas import BancoDadosConfigIn

router = APIRouter(prefix="/admin/banco-dados", tags=["Admin - Banco de Dados"])


@router.get("")
def obter_config_atual(usuario: dict = Depends(exigir_admin)):
    """Config ativa agora — nunca devolve a senha (ver
    db_conexao.config_sem_senha)."""
    return db_conexao.config_sem_senha()


def _cfg_com_senha_atual(cfg: dict) -> dict:
    """Se o campo `senha` vier vazio no formulário, reaproveita a senha já
    salva na config ativa. A tela sempre limpa esse campo e só mostra
    "(mantida — digite pra trocar)" como placeholder (ver GET, que nunca
    ecoa a senha de volta pro navegador) — sem isso, testar/aplicar sem
    redigitar a senha sobrescreveria (ou testaria com) uma senha vazia em
    vez da que já estava configurada."""
    if cfg.get("senha"):
        return cfg
    senha_atual = db_conexao.carregar_config().get("senha")
    if senha_atual:
        cfg = dict(cfg)
        cfg["senha"] = senha_atual
    return cfg


def _conectar_ou_422(cfg: dict):
    try:
        return db_conexao.conectar(cfg, sqlite_path_padrao=db.DB_PATH)
    except db_conexao.ErroConexaoBanco as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:  # driver pode levantar exceção própria não mapeada
        raise HTTPException(status_code=422, detail=f"Falha ao conectar: {e}") from e


@router.post("/testar")
def testar_conexao(payload: BancoDadosConfigIn, usuario: dict = Depends(exigir_admin)):
    """Tenta abrir a conexão com a config recebida SEM aplicar nada —
    não muda o banco em uso, não mexe em schema nem dado nenhum."""
    conn = _conectar_ou_422(_cfg_com_senha_atual(payload.model_dump()))
    try:
        conn.execute("SELECT 1").fetchone()
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Conectou, mas a checagem falhou: {e}") from e
    finally:
        conn.close()
    return {"status": "ok", "mensagem": "Conexão bem-sucedida."}


@router.post("/aplicar")
def aplicar_config(payload: BancoDadosConfigIn, usuario: dict = Depends(exigir_admin)):
    """Cria o schema no banco novo, migra todos os dados do banco atual
    pra ele, e só então troca a config ativa. Se qualquer etapa falhar,
    o banco em uso continua sendo o de antes (nada é trocado até o
    final)."""
    cfg = _cfg_com_senha_atual(payload.model_dump())
    tipo = cfg["tipo"]

    conn_destino = _conectar_ou_422(cfg)
    try:
        if tipo == "sqlite":
            conn_destino.executescript(db.SCHEMA)
            db._migrar_colunas(conn_destino)
        else:
            conn_destino.executescript(db._gerar_schema_consolidado(tipo))
        conn_destino.commit()

        with db.get_connection() as conn_origem:
            dados = db_conexao.exportar_todas_tabelas(conn_origem)

        resultado = db_conexao.importar_todas_tabelas(conn_destino, dados)
        conn_destino.commit()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Falha ao migrar dados pro banco novo: {e}") from e
    finally:
        conn_destino.close()

    # Só troca a config ativa (e recarrega os parâmetros em memória a
    # partir dela) depois que schema + dados no destino já deram certo.
    db_conexao.salvar_config(cfg)
    fs.carregar_parametros()
    return {"status": "ok", "linhas_migradas": resultado}
