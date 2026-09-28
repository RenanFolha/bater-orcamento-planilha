# Desenvolvedor Chefe: RenanFolha

"""
Camada de conexão com o banco de dados: por padrão o sistema roda com
SQLite (arquivo local, como sempre funcionou), mas pode ser configurado
pela tela Configurações → "Banco de dados" (ver routers/admin_banco.py)
pra apontar pra um servidor SQL Server, MySQL ou PostgreSQL.

De propósito, este módulo NÃO usa ORM/SQLAlchemy: quase toda checagem de
conflito do projeto já é feita pela própria aplicação (SELECT antes do
INSERT, não pela constraint do banco — ver frete_db.py) e o SQL usado em
todo o projeto é ANSI padrão (SELECT/INSERT/UPDATE/DELETE/WHERE/JOIN/
LOWER()). Então basta uma camada fina por dialeto na hora de abrir a
conexão e traduzir o placeholder "?" — as ~100 funções de CRUD de
frete_db.py continuam exatamente iguais, sem saber qual driver está por
trás.

A config de qual banco usar fica em `db_config.json` (fora do git — pode
ter host/usuário de um servidor externo). O campo `senha` é gravado
cifrado (Fernet/AES) com uma chave local gerada na primeira vez em
`db_config.key` (também fora do git, ver `_obter_chave`) — nunca em
texto puro no arquivo. Sem `db_config.json` (instalação nova ou já
existente), o padrão é SQLite apontando pro caminho de sempre
(frete_db.DB_PATH) — ninguém precisa mexer na tela nova pra continuar
exatamente como estava.
"""

import json
import os
import sqlite3

from cryptography.fernet import Fernet, InvalidToken

TIPOS_BANCO = ("sqlite", "sqlserver", "mysql", "postgresql")

DB_CONFIG_PATH = os.environ.get(
    "FRETE_DB_CONFIG_PATH",
    os.path.join(os.path.dirname(__file__), "db_config.json"),
)

DB_CONFIG_KEY_PATH = os.environ.get(
    "FRETE_DB_CONFIG_KEY_PATH",
    os.path.join(os.path.dirname(__file__), "db_config.key"),
)


def _obter_chave() -> bytes:
    """Chave simétrica local usada só pra cifrar/decifrar o campo `senha`
    de db_config.json. Gerada e salva em DB_CONFIG_KEY_PATH na primeira
    vez que alguém salva uma config com senha; depois disso é sempre
    reaproveitada (perder o arquivo da chave torna qualquer senha já
    salva ilegível, exigindo recadastro pela tela)."""
    if os.path.exists(DB_CONFIG_KEY_PATH):
        with open(DB_CONFIG_KEY_PATH, "rb") as f:
            return f.read().strip()
    chave = Fernet.generate_key()
    with open(DB_CONFIG_KEY_PATH, "wb") as f:
        f.write(chave)
    return chave


def _cifrar_senha(senha: str) -> str:
    if not senha:
        return ""
    return Fernet(_obter_chave()).encrypt(senha.encode("utf-8")).decode("ascii")


def _decifrar_senha(senha: str) -> str:
    """Decifra o valor gravado em disco. Se não for um token Fernet
    válido (ex: db_config.json de uma versão anterior a esta mudança,
    com a senha ainda em texto puro), devolve o valor como veio — a
    próxima chamada a salvar_config já regrava cifrado."""
    if not senha:
        return ""
    try:
        return Fernet(_obter_chave()).decrypt(senha.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return senha


class ConflitoIntegridade(Exception):
    """Levantada quando uma escrita violaria uma regra de unicidade do
    domínio (rota duplicada, praça repetida etc.). Substitui
    sqlite3.IntegrityError como a exceção "pública" que o resto do
    projeto (deps.py, routers/*, testes) espera — com múltiplos bancos
    possíveis não dá mais pra assumir qual driver (e portanto qual tipo
    de exceção nativa) está ativo."""


class ErroConexaoBanco(Exception):
    """Erro ao conectar/configurar o banco — mensagem já pronta pra
    mostrar na tela (driver não instalado, credenciais erradas, host
    inacessível etc.), usado pelos endpoints de /admin/banco-dados."""


def config_padrao() -> dict:
    """sqlite_path vazio == "não sobrescrito, use frete_db.DB_PATH"; é
    frete_db.py que decide o caminho final (get_connection), porque é lá
    que o caminho de teste (fixture banco_temporario) faz monkeypatch —
    esse módulo não pode ter uma cópia própria do default, senão o
    monkeypatch do teste para de fazer efeito."""
    return {
        "tipo": "sqlite",
        "sqlite_path": "",
        "host": "",
        "porta": 0,
        "banco": "",
        "usuario": "",
        "senha": "",
    }


def carregar_config() -> dict:
    if not os.path.exists(DB_CONFIG_PATH):
        return config_padrao()
    with open(DB_CONFIG_PATH, encoding="utf-8") as f:
        dados = json.load(f)
    cfg = config_padrao()
    cfg.update(dados)
    cfg["senha"] = _decifrar_senha(cfg.get("senha", ""))
    return cfg


def salvar_config(cfg: dict) -> None:
    cfg_para_salvar = dict(cfg)
    cfg_para_salvar["senha"] = _cifrar_senha(cfg.get("senha", ""))
    with open(DB_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg_para_salvar, f, ensure_ascii=False, indent=2)


def config_sem_senha(cfg: dict | None = None) -> dict:
    """Versão da config segura pra devolver numa resposta de API — nunca
    ecoa a senha de volta pro navegador."""
    cfg = dict(cfg if cfg is not None else carregar_config())
    tem_senha = bool(cfg.get("senha"))
    cfg.pop("senha", None)
    cfg["senha_configurada"] = tem_senha
    return cfg


def _traduzir_placeholders(sql: str, paramstyle: str) -> str:
    """Converte o SQL escrito com "?" (paramstyle qmark, usado em todo o
    frete_db.py) pro paramstyle nativo do driver. sqlite3 e pyodbc já
    usam qmark (sem tradução); pymysql ("format") e psycopg2
    ("pyformat") aceitam "%s" posicional igualmente, então uma troca
    direta "?" -> "%s" cobre os dois. Seguro pra esse projeto porque
    nenhuma string SQL aqui tem "?" dentro de um literal — só como
    placeholder de parâmetro."""
    if paramstyle == "qmark":
        return sql
    return sql.replace("?", "%s")


class _LinhaDict(dict):
    """Faz uma linha de cursor (tupla + descrição) se comportar como
    sqlite3.Row: indexável por nome de coluna (`row["campo"]`) e também
    virar dict puro (`dict(row)`), que é o padrão usado em quase toda
    função de listagem do frete_db.py."""


def _montar_linha(descricao, valores) -> _LinhaDict:
    colunas = [c[0] for c in descricao]
    return _LinhaDict(zip(colunas, valores, strict=True))


class _CursorAdaptado:
    """Espelha a superfície de um cursor sqlite3 usada em frete_db.py:
    `.fetchone()`, `.fetchall()`, iteração direta e `.lastrowid`."""

    def __init__(self, cursor):
        self._cursor = cursor

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    def fetchone(self):
        linha = self._cursor.fetchone()
        if linha is None or self._cursor.description is None:
            return linha
        return _montar_linha(self._cursor.description, linha)

    def fetchall(self):
        linhas = self._cursor.fetchall()
        if self._cursor.description is None:
            return linhas
        return [_montar_linha(self._cursor.description, r) for r in linhas]

    def __iter__(self):
        return iter(self.fetchall())


class _ConexaoAdaptada:
    """Faz uma conexão de pyodbc/pymysql/psycopg2 se comportar, pro resto
    do frete_db.py, como a conexão sqlite3 de sempre: `.execute(sql,
    params)` aceita "?" como placeholder mesmo quando o driver de baixo
    exige outro paramstyle, e devolve linhas indexáveis por nome de
    coluna."""

    def __init__(self, conexao_nativa, paramstyle: str):
        self._conexao = conexao_nativa
        self._paramstyle = paramstyle

    def execute(self, sql, params=()):
        cursor = self._conexao.cursor()
        cursor.execute(_traduzir_placeholders(sql, self._paramstyle), tuple(params))
        return _CursorAdaptado(cursor)

    def executemany(self, sql, lista_params):
        cursor = self._conexao.cursor()
        cursor.executemany(_traduzir_placeholders(sql, self._paramstyle), [tuple(p) for p in lista_params])
        return _CursorAdaptado(cursor)

    def executescript(self, script: str):
        # Só sqlite3 tem executescript nativo -- os outros drivers
        # executam um comando por vez, então separamos por ";" (o schema
        # deste projeto não usa ";" dentro de string/valor nenhuma vez,
        # então é seguro).
        cursor = self._conexao.cursor()
        for trecho in script.split(";"):
            trecho = trecho.strip()
            if trecho:
                cursor.execute(trecho)

    def commit(self):
        self._conexao.commit()

    def rollback(self):
        self._conexao.rollback()

    def close(self):
        self._conexao.close()


def conectar(cfg: dict | None = None, *, sqlite_path_padrao: str | None = None):
    """Abre uma conexão pro banco configurado. `sqlite_path_padrao` é o
    caminho a usar quando tipo == "sqlite" e a config não tiver
    `sqlite_path` preenchido (ver frete_db.get_connection, que passa
    `db.DB_PATH` aqui — é isso que mantém o monkeypatch dos testes
    funcionando)."""
    cfg = cfg if cfg is not None else carregar_config()
    tipo = cfg.get("tipo", "sqlite")

    if tipo == "sqlite":
        caminho = cfg.get("sqlite_path") or sqlite_path_padrao
        if not caminho:
            raise ErroConexaoBanco("Caminho do arquivo SQLite não informado.")
        conn = sqlite3.connect(caminho)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    if tipo == "sqlserver":
        try:
            import pyodbc
        except ImportError as e:
            raise ErroConexaoBanco(
                "Driver 'pyodbc' não instalado (pip install pyodbc) — também exige o "
                "ODBC Driver 17/18 for SQL Server instalado no sistema operacional."
            ) from e
        conn_str = (
            "DRIVER={ODBC Driver 17 for SQL Server};"
            f"SERVER={cfg.get('host', '')},{int(cfg.get('porta') or 1433)};"
            f"DATABASE={cfg.get('banco', '')};UID={cfg.get('usuario', '')};PWD={cfg.get('senha', '')};"
            "TrustServerCertificate=yes;"
        )
        try:
            nativa = pyodbc.connect(conn_str, autocommit=False, timeout=10)
        except pyodbc.Error as e:
            raise ErroConexaoBanco(f"Falha ao conectar no SQL Server: {e}") from e
        return _ConexaoAdaptada(nativa, pyodbc.paramstyle)

    if tipo == "mysql":
        try:
            import pymysql
        except ImportError as e:
            raise ErroConexaoBanco("Driver 'pymysql' não instalado (pip install pymysql).") from e
        try:
            nativa = pymysql.connect(
                host=cfg.get("host", ""), port=int(cfg.get("porta") or 3306),
                user=cfg.get("usuario", ""), password=cfg.get("senha", ""),
                database=cfg.get("banco", ""), autocommit=False, connect_timeout=10,
            )
        except pymysql.MySQLError as e:
            raise ErroConexaoBanco(f"Falha ao conectar no MySQL: {e}") from e
        return _ConexaoAdaptada(nativa, pymysql.paramstyle)

    if tipo == "postgresql":
        try:
            import psycopg2
        except ImportError as e:
            raise ErroConexaoBanco("Driver 'psycopg2' não instalado (pip install psycopg2-binary).") from e
        try:
            nativa = psycopg2.connect(
                host=cfg.get("host", ""), port=int(cfg.get("porta") or 5432),
                user=cfg.get("usuario", ""), password=cfg.get("senha", ""),
                dbname=cfg.get("banco", ""), connect_timeout=10,
            )
        except psycopg2.Error as e:
            raise ErroConexaoBanco(f"Falha ao conectar no PostgreSQL: {e}") from e
        return _ConexaoAdaptada(nativa, psycopg2.paramstyle)

    raise ErroConexaoBanco(f"Tipo de banco desconhecido: {tipo!r}")


def _erros_integridade_nativos() -> tuple:
    """Tupla de exceções de violação de constraint de cada driver
    instalado — usada como rede de segurança em frete_db.get_connection
    pra cobrir uma violação real do banco (corrida entre duas escritas
    concorrentes), não só a checagem manual que a aplicação já faz antes
    de cada INSERT/UPDATE."""
    erros = [sqlite3.IntegrityError]
    for nome_modulo in ("pyodbc", "pymysql", "psycopg2"):
        try:
            modulo = __import__(nome_modulo)
        except ImportError:
            continue
        if hasattr(modulo, "IntegrityError"):
            erros.append(modulo.IntegrityError)
    return tuple(erros)


ERROS_INTEGRIDADE_NATIVOS = _erros_integridade_nativos()


# Ordem de exportação/importação segura por FK — tabelas sem dependência
# primeiro, dependentes depois (ver exportar_todas_tabelas/
# importar_todas_tabelas em frete_db.py). As duas únicas relações de FK
# do schema hoje são usuarios->sessoes e pracas_pedagio->pedagios_rota.
ORDEM_TABELAS = (
    "faixas_peso", "faixas_distancia", "faixas_coleta",
    "categorias", "transportes", "slas", "filiais", "veiculos",
    "faixas_km_veiculo", "taxas_adicionais", "coleta_cidades_fixas",
    "transportadoras_terceirizadas", "taxas_regionais", "taxas_balsa",
    "prioridades_rota", "aliquotas_icms", "aliquota_pis_cofins", "pracas_pedagio", "pedagios_rota", "distancias_fixas",
    "usuarios", "sessoes", "orcamentos_historico",
)


def exportar_todas_tabelas(conn) -> dict:
    """Lê todas as linhas de todas as tabelas conhecidas, na ordem segura
    de FK (pais antes de filhos) -- usado pra migrar do banco atual pro
    banco novo escolhido na tela (ver POST /admin/banco-dados/aplicar)."""
    dados = {}
    for tabela in ORDEM_TABELAS:
        linhas = conn.execute(f"SELECT * FROM {tabela}").fetchall()
        dados[tabela] = [dict(r) for r in linhas]
    return dados


def importar_todas_tabelas(conn, dados: dict) -> dict:
    """Insere as linhas exportadas por exportar_todas_tabelas no banco de
    destino (schema já precisa existir -- ver init_db), mesma ordem
    segura de FK. Devolve {tabela: quantidade_inserida}. Assume que o
    destino está vazio (chamado logo depois de criar o schema do zero em
    POST /admin/banco-dados/aplicar) -- não faz upsert."""
    resultado = {}
    for tabela in ORDEM_TABELAS:
        linhas = dados.get(tabela) or []
        resultado[tabela] = len(linhas)
        if not linhas:
            continue
        colunas = list(linhas[0].keys())
        placeholders = ",".join("?" for _ in colunas)
        sql = f"INSERT INTO {tabela} ({','.join(colunas)}) VALUES ({placeholders})"
        conn.executemany(sql, [tuple(linha[c] for c in colunas) for linha in linhas])
    return resultado
