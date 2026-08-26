"""
Banco de dados SQLite com todos os parâmetros do sistema de frete.

Substitui a antiga planilha Excel. O arquivo `frete.db` pode ser aberto
e editado diretamente com o DB Browser for SQLite (https://sqlitebrowser.org/,
gratuito) — não precisa de nenhuma API especial para alterar preços,
faixas, filiais etc.

As faixas de peso e distância têm uma coluna "tipo_frete" (ex.:
"Fracionado", "Carreta Fechada") — cada tipo tem sua própria tabela de
preços, mas usa a mesma fórmula de cálculo. Para cadastrar um novo tipo
de frete, basta inserir novas linhas em faixas_peso/faixas_distancia com
um "tipo_frete" novo — ele aparece automaticamente no sistema, sem
precisar mexer em código.

Na primeira execução, se o banco não existir, ele é criado
automaticamente com dados de exemplo, prontos para você editar. Se o
banco já existir de uma versão anterior (sem a coluna tipo_frete), ela é
adicionada automaticamente na inicialização, sem apagar nada que já
estava lá.
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

DB_PATH = os.environ.get(
    "FRETE_DB_PATH",
    os.path.join(os.path.dirname(__file__), "frete.db"),
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS faixas_peso (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo_frete TEXT NOT NULL DEFAULT 'Fracionado',
    de REAL NOT NULL,
    ate REAL NOT NULL,
    tarifa_base REAL NOT NULL,
    custo_kg_adicional REAL NOT NULL DEFAULT 0,
    observacao TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS faixas_distancia (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo_frete TEXT NOT NULL DEFAULT 'Fracionado',
    de REAL NOT NULL,
    ate REAL NOT NULL,
    taxa_fixa REAL NOT NULL,
    tarifa_km REAL NOT NULL DEFAULT 0,
    observacao TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS faixas_coleta (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    de REAL NOT NULL,
    ate REAL NOT NULL,
    taxa_fixa REAL NOT NULL,
    tarifa_km REAL NOT NULL DEFAULT 0,
    observacao TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS categorias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL UNIQUE,
    multiplicador REAL NOT NULL,
    observacao TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS transportes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL UNIQUE,
    multiplicador REAL NOT NULL,
    fator_cubagem REAL NOT NULL,
    observacao TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS slas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL UNIQUE,
    multiplicador REAL NOT NULL,
    prazo_dias INTEGER NOT NULL,
    observacao TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS filiais (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL UNIQUE,
    endereco TEXT NOT NULL,
    latitude REAL,
    longitude REAL
);

CREATE TABLE IF NOT EXISTS veiculos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL UNIQUE,
    de REAL NOT NULL DEFAULT 0,
    ate REAL NOT NULL DEFAULT 999999,
    tarifa_km REAL NOT NULL,
    peso_incluso_kg REAL NOT NULL DEFAULT 0,
    valor_kg_excedente REAL NOT NULL DEFAULT 0,
    tarifa_km_retorno REAL NOT NULL DEFAULT 0,
    tarifa_km_manutencao REAL NOT NULL DEFAULT 0,
    capacidade_m3 REAL NOT NULL DEFAULT 0,
    -- % de capacidade_m3 que pode ser ocupada de verdade (o resto é
    -- margem — carga não empilha 100%, precisa espaço pra amarração
    -- etc.). Editável por veículo; era um valor fixo de 80% no código
    -- antes de existir essa coluna.
    percentual_capacidade_util REAL NOT NULL DEFAULT 80,
    observacao TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS taxas_adicionais (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL UNIQUE,
    tipo TEXT NOT NULL DEFAULT 'fixo' CHECK (tipo IN ('fixo', 'percentual')),
    valor REAL NOT NULL DEFAULT 0,
    observacao TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS coleta_cidades_fixas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filial_origem TEXT NOT NULL,
    -- Uma ou mais cidades separadas por vírgula (ex: "Osasco, Barueri,
    -- Cotia") — uma linha só cobre várias cidades do cliente, em vez de
    -- precisar de uma linha por cidade. Sem UNIQUE aqui de propósito: a
    -- checagem de cidade duplicada (mesma cidade em duas linhas do mesmo
    -- filial_origem+veiculo) é feita em Python (ver
    -- _cidades_coleta_conflitantes), porque a lista embutida no texto não
    -- dá pra validar com um UNIQUE simples do SQLite.
    cidade_destino TEXT NOT NULL,
    veiculo TEXT NOT NULL,
    valor_fixo REAL NOT NULL,
    observacao TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS transportadoras_terceirizadas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    cidade TEXT NOT NULL,
    tipo TEXT NOT NULL DEFAULT 'ambos' CHECK (tipo IN ('coleta', 'entrega', 'ambos')),
    valor REAL NOT NULL,
    observacao TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS taxas_regionais (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cidade TEXT NOT NULL,
    nome TEXT NOT NULL,
    tipo TEXT NOT NULL DEFAULT 'fixo' CHECK (tipo IN ('fixo', 'percentual')),
    valor REAL NOT NULL,
    observacao TEXT DEFAULT '',
    UNIQUE(cidade, nome)
);

CREATE TABLE IF NOT EXISTS taxas_balsa (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Direcional de propósito (cidade_origem -> cidade_destino): o preço da
    -- travessia pode ser diferente na ida e na volta, então cada linha só
    -- vale naquela direção específica — cadastre 2 linhas se ida e volta
    -- tiverem valores diferentes. O valor também pode mudar por veículo
    -- (balsa cobra por categoria do veículo embarcado).
    cidade_origem TEXT NOT NULL,
    cidade_destino TEXT NOT NULL,
    veiculo TEXT NOT NULL,
    tipo TEXT NOT NULL DEFAULT 'fixo' CHECK (tipo IN ('fixo', 'percentual')),
    valor REAL NOT NULL,
    observacao TEXT DEFAULT '',
    UNIQUE(cidade_origem, cidade_destino, veiculo)
);

CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    username TEXT NOT NULL UNIQUE,
    senha_hash TEXT NOT NULL,
    senha_salt TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'usuario' CHECK (role IN ('admin', 'usuario')),
    ativo INTEGER NOT NULL DEFAULT 1,
    criado_em TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS sessoes (
    token TEXT PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    criado_em TEXT NOT NULL,
    expira_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orcamentos_historico (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    criado_em TEXT NOT NULL,
    cliente TEXT NOT NULL DEFAULT '',
    responsavel TEXT NOT NULL DEFAULT '',
    origem_resumo TEXT DEFAULT '',
    destino_resumo TEXT DEFAULT '',
    veiculo TEXT DEFAULT '',
    distancia_km REAL DEFAULT 0,
    valor_mercadoria REAL DEFAULT 0,
    frete_total REAL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'Fechado',
    dados_json TEXT NOT NULL DEFAULT '{}',
    criado_por TEXT NOT NULL DEFAULT ''
);
"""


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _seed_se_vazio(conn: sqlite3.Connection):
    """Popula o banco com dados de exemplo apenas se as tabelas estiverem vazias
    (não sobrescreve edições feitas manualmente)."""

    if conn.execute("SELECT COUNT(*) FROM faixas_peso").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO faixas_peso (tipo_frete, de, ate, tarifa_base, custo_kg_adicional, observacao) VALUES (?,?,?,?,?,?)",
            [
                ("Fracionado", 0, 5, 15.00, 0.00, "Faixa mínima / encomendas pequenas"),
                ("Fracionado", 5, 10, 25.00, 2.50, ""),
                ("Fracionado", 10, 30, 45.00, 2.00, ""),
                ("Fracionado", 30, 100, 95.00, 1.80, "Carga fracionada"),
                ("Fracionado", 100, 999999, 250.00, 1.50, "Carga pesada"),
                # Carreta fechada: valores de exemplo — ajuste para a realidade
                # da sua operação (geralmente cobrada por caminhão/viagem, não
                # por faixas pequenas de peso).
                ("Carreta Fechada", 0, 8000, 1800.00, 0.00, "Carreta fechada — até 8 toneladas (exemplo, ajuste)"),
                ("Carreta Fechada", 8000, 15000, 2600.00, 0.05, "Carreta fechada — até 15 toneladas (exemplo, ajuste)"),
                ("Carreta Fechada", 15000, 999999, 3800.00, 0.03, "Carreta fechada — acima de 15 toneladas (exemplo, ajuste)"),
            ],
        )

    if conn.execute("SELECT COUNT(*) FROM faixas_distancia").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO faixas_distancia (tipo_frete, de, ate, taxa_fixa, tarifa_km, observacao) VALUES (?,?,?,?,?,?)",
            [
                ("Fracionado", 0, 50, 10.00, 0.50, "Local / mesma região"),
                ("Fracionado", 50, 200, 20.00, 0.40, ""),
                ("Fracionado", 200, 500, 40.00, 0.30, ""),
                ("Fracionado", 500, 1500, 80.00, 0.22, "Interestadual"),
                ("Fracionado", 1500, 999999, 150.00, 0.15, "Longa distância"),
                # Carreta fechada: valores de exemplo — ajuste conforme sua tabela real.
                ("Carreta Fechada", 0, 200, 300.00, 4.50, "Carreta fechada — regional (exemplo, ajuste)"),
                ("Carreta Fechada", 200, 800, 500.00, 3.80, "Carreta fechada — interestadual (exemplo, ajuste)"),
                ("Carreta Fechada", 800, 999999, 900.00, 3.20, "Carreta fechada — longa distância (exemplo, ajuste)"),
            ],
        )

    if conn.execute("SELECT COUNT(*) FROM faixas_coleta").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO faixas_coleta (de, ate, taxa_fixa, tarifa_km, observacao) VALUES (?,?,?,?,?)",
            [
                (0, 10, 15.00, 3.00, "Coleta local, valores de exemplo — ajuste"),
                (10, 30, 25.00, 2.50, ""),
                (30, 80, 45.00, 2.00, ""),
                (80, 999999, 80.00, 1.80, "Coleta de longa distância"),
            ],
        )

    if conn.execute("SELECT COUNT(*) FROM categorias").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO categorias (nome, multiplicador, observacao) VALUES (?,?,?)",
            [
                ("Geral", 1.00, "Produtos padrão, sem cuidado especial"),
                ("Frágil", 1.30, "Vidro, cerâmica, eletrodomésticos"),
                ("Eletrônicos", 1.20, "Maior valor agregado / risco de furto"),
                ("Perecível", 1.50, "Requer transporte rápido / refrigeração"),
                ("Perigoso / Químico", 1.80, "Exige manuseio e documentação especial"),
            ],
        )

    if conn.execute("SELECT COUNT(*) FROM transportes").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO transportes (nome, multiplicador, fator_cubagem, observacao) VALUES (?,?,?,?)",
            [
                ("Rodoviário", 1.00, 3000, "Padrão para cargas nacionais"),
                ("Aéreo", 2.50, 6000, "Mais rápido e mais caro")
            ],
        )

    if conn.execute("SELECT COUNT(*) FROM slas").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO slas (nome, multiplicador, prazo_dias, observacao) VALUES (?,?,?,?)",
            [
                ("Econômico", 0.90, 10, "Sem urgência, menor custo"),
                ("Padrão", 1.00, 5, "Prazo normal"),
                ("Expresso", 1.50, 2, "Entrega prioritária"),
                ("Urgente", 2.20, 1, "Entrega no dia seguinte"),
            ],
        )

    if conn.execute("SELECT COUNT(*) FROM filiais").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO filiais (nome, endereco) VALUES (?,?)",
            [
                ("São Paulo", "Av. Otaviano Alves de Lima, nº 2724 Bloco B-4° Andar, bairro Jardim das Graças / CEP: 02.701-000"),
                ("Campinas", "Av. Br Smith Vasconcelos, nº 630, Prédio 3, bairro Distrito Industrial / CEP: 13054-740"),
                ("Manaus", "Rua Matrinxã, nº 1.111-C, bairro Distrito Industrial I / CEP: 69.075-150"),
                ("Belém", "Centro, Belém, PA, Brasil"),
                ("Itu", "Rodovia Waldomiro Correa de Camargo, KM 54.3, Galpão 02, bairro Vila Martins/CEP: 13.308-200" ),
                ("Varginha","Av. Murilo Paiva, nº 460, Sala A - bairro Parque Mariela / CEP: 37.030-000"),
                ("Serra","Rua Francisco Sousa dos Santos, n° 456 B, Quadra CHA - Lote 374, bairro Jardim Limoeiro / CEP: 29.164-153"),
                ("Ananindeua", "Rodovia BR 316, nº 5100 - Km 05 Cond. CPX Galpões Carisma - Galpão 08A, bairro Coqueiro /  CEP: 67.015-220"),
                ("Cabo Santo Agostinho", "Rodovia, BR 101 Sul km 96,4 nº 5.225, Condomínio Logístico Cone Multimodal 1, Galpão 8, Bairro Distrito Industrial Diper / CEP: 54.503-410"),
                ("São José dos Pinhais", "Rodovia, BR 376, KM 14, nº 16.099 sala 1, nº São Marcos / CEP: 83.090-360"),
                ("Joinville", "Rua Rui Barbosa, n° 3601, Sala 01 - bairro Costa e Silva / CEP: 89.220-101"),
            ],
        )
        # ATENÇÃO: endereços de exemplo — edite na tabela "filiais" com o
        # endereço completo e real de cada filial (rua, número, bairro,
        # cidade, UF) para que o cálculo de distância seja preciso.

    if conn.execute("SELECT COUNT(*) FROM veiculos").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO veiculos (nome, de, ate, tarifa_km, peso_incluso_kg, valor_kg_excedente, capacidade_m3, observacao) VALUES (?,?,?,?,?,?,?,?)",
            [
                ("Caminhonete", 0, 750, 2.00, 400, 1.50, 2.5, "Valores de exemplo — ajuste na Tabela de Preços"),
                ("Van / HR", 750, 1500, 2.60, 800, 1.10, 8.0, "Valores de exemplo — ajuste"),
                ("VUC", 1500, 3500, 3.20, 1500, 0.80, 15.0, "Valores de exemplo — ajuste"),
                ("Truck / Toco (Caminhão 3/4)", 3500, 8000, 4.80, 6000, 0.45, 35.0, "Valores de exemplo — ajuste"),
                ("Carreta", 8000, 999999, 5.50, 15000, 0.35, 90.0, "Valores de exemplo — ajuste"),
            ],
        )

    if conn.execute("SELECT COUNT(*) FROM taxas_adicionais").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO taxas_adicionais (nome, tipo, valor, observacao) VALUES (?,?,?,?)",
            [
                ("GRIS", "percentual", 0.30, "Gerenciamento de risco — % sobre o valor da mercadoria (exemplo, ajuste)"),
                ("Ad Valorem", "percentual", 0.50, "% sobre o valor da mercadoria (exemplo, ajuste)"),
                ("Pedágio", "fixo", 18.00, "Valor fixo em R$ (exemplo, ajuste)"),
                ("Taxa de Localidade", "fixo", 25.00, "Áreas de dificil acesso — valor fixo em R$ (exemplo, ajuste)"),
            ],
        )
    # coleta_cidades_fixas começa vazia de propósito — só cadastre as
    # cidades onde a coleta tem preço fixo; as demais continuam usando
    # a tabela "Faixas de Coleta" por km normalmente.
    # transportadoras_terceirizadas também começa vazia — cadastre lá
    # as transportadoras terceirizadas de coleta/entrega com o valor
    # combinado por cidade, quando a operação não for feita pela frota
    # própria.


def _coluna_existe(conn: sqlite3.Connection, tabela: str, coluna: str) -> bool:
    colunas = {row["name"] for row in conn.execute(f"PRAGMA table_info({tabela})")}
    return coluna in colunas


def _migrar_coleta_cidades_fixas_lista(conn: sqlite3.Connection):
    """coleta_cidades_fixas passou a aceitar uma LISTA de cidades separadas
    por vírgula em `cidade_destino` (uma linha cobre várias cidades do
    cliente), em vez de uma linha por cidade. Isso exige remover a antiga
    UNIQUE(filial_origem, cidade_destino, veiculo) — o SQLite não tem ALTER
    TABLE DROP CONSTRAINT, então recriamos a tabela preservando todas as
    linhas e ids existentes (cada cidade já cadastrada vira uma "lista de
    1" automaticamente, sem perda de dado)."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='coleta_cidades_fixas'"
    ).fetchone()
    if not row or "UNIQUE(filial_origem, cidade_destino, veiculo)" not in (row["sql"] or ""):
        return  # já migrado
    conn.execute("ALTER TABLE coleta_cidades_fixas RENAME TO coleta_cidades_fixas_old")
    conn.execute("""
        CREATE TABLE coleta_cidades_fixas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filial_origem TEXT NOT NULL,
            cidade_destino TEXT NOT NULL,
            veiculo TEXT NOT NULL,
            valor_fixo REAL NOT NULL,
            observacao TEXT DEFAULT ''
        )
    """)
    conn.execute("""
        INSERT INTO coleta_cidades_fixas (id, filial_origem, cidade_destino, veiculo, valor_fixo, observacao)
        SELECT id, filial_origem, cidade_destino, veiculo, valor_fixo, observacao FROM coleta_cidades_fixas_old
    """)
    conn.execute("DROP TABLE coleta_cidades_fixas_old")


def _migrar_colunas(conn: sqlite3.Connection):
    """Para bancos criados antes de existir a coluna tipo_frete:
    adiciona a coluna sem apagar nada do que já estava lá. Também remove
    a tabela parametros_gerais (frete mínimo/seguro/imposto), que deixou
    de existir — o cálculo de frete não usa mais esses valores."""
    for tabela in ("faixas_peso", "faixas_distancia"):
        if not _coluna_existe(conn, tabela, "tipo_frete"):
            conn.execute(
                f"ALTER TABLE {tabela} ADD COLUMN tipo_frete TEXT NOT NULL DEFAULT 'Fracionado'"
            )
    conn.execute("DROP TABLE IF EXISTS parametros_gerais")
    # coleta_cidades_fixas mudou de "1 preço por cidade" pra "1 preço por
    # rota (filial de origem -> cidade do cliente) + veículo". O schema
    # antigo é incompatível com o novo — como só existia 1 linha de
    # teste, recriamos a tabela em vez de migrar dado.
    if not _coluna_existe(conn, "coleta_cidades_fixas", "filial_origem"):
        conn.execute("DROP TABLE IF EXISTS coleta_cidades_fixas")
        conn.execute("""
            CREATE TABLE coleta_cidades_fixas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filial_origem TEXT NOT NULL,
                cidade_destino TEXT NOT NULL,
                veiculo TEXT NOT NULL,
                valor_fixo REAL NOT NULL,
                observacao TEXT DEFAULT ''
            )
        """)
    else:
        _migrar_coleta_cidades_fixas_lista(conn)
    if not _coluna_existe(conn, "veiculos", "de"):
        conn.execute("ALTER TABLE veiculos ADD COLUMN de REAL NOT NULL DEFAULT 0")
    if not _coluna_existe(conn, "veiculos", "ate"):
        conn.execute("ALTER TABLE veiculos ADD COLUMN ate REAL NOT NULL DEFAULT 999999")
    if not _coluna_existe(conn, "veiculos", "tarifa_km_retorno"):
        conn.execute("ALTER TABLE veiculos ADD COLUMN tarifa_km_retorno REAL NOT NULL DEFAULT 0")
    if not _coluna_existe(conn, "veiculos", "tarifa_km_manutencao"):
        conn.execute("ALTER TABLE veiculos ADD COLUMN tarifa_km_manutencao REAL NOT NULL DEFAULT 0")
    if not _coluna_existe(conn, "veiculos", "capacidade_m3"):
        conn.execute("ALTER TABLE veiculos ADD COLUMN capacidade_m3 REAL NOT NULL DEFAULT 0")
    if not _coluna_existe(conn, "veiculos", "percentual_capacidade_util"):
        conn.execute("ALTER TABLE veiculos ADD COLUMN percentual_capacidade_util REAL NOT NULL DEFAULT 80")
    if not _coluna_existe(conn, "orcamentos_historico", "criado_por"):
        # Registra qual conta de login efetivamente salvou o registro —
        # distinto de "responsavel" (texto livre, quem o usuário diz ser o
        # responsável pelo orçamento). Usado só para controlar quem pode
        # excluir o registro (dono ou admin), sem mudar o campo visível
        # "Responsável" que já existia. Bancos antigos ficam com '' (só
        # admin consegue excluir esses registros legados).
        conn.execute("ALTER TABLE orcamentos_historico ADD COLUMN criado_por TEXT NOT NULL DEFAULT ''")


def _completar_carreta_fechada(conn: sqlite3.Connection):
    """Se o tipo 'Carreta Fechada' ainda não tem nenhuma faixa cadastrada
    (banco de uma versão anterior que só tinha Fracionado), cadastra
    faixas de exemplo para ele — edite os valores depois."""

    tem_carreta_peso = conn.execute(
        "SELECT COUNT(*) FROM faixas_peso WHERE tipo_frete = 'Carreta Fechada'"
    ).fetchone()[0]
    if tem_carreta_peso == 0:
        conn.executemany(
            "INSERT INTO faixas_peso (tipo_frete, de, ate, tarifa_base, custo_kg_adicional, observacao) VALUES (?,?,?,?,?,?)",
            [
                ("Carreta Fechada", 0, 8000, 1800.00, 0.00, "Carreta fechada — até 8 toneladas (exemplo, ajuste)"),
                ("Carreta Fechada", 8000, 15000, 2600.00, 0.05, "Carreta fechada — até 15 toneladas (exemplo, ajuste)"),
                ("Carreta Fechada", 15000, 999999, 3800.00, 0.03, "Carreta fechada — acima de 15 toneladas (exemplo, ajuste)"),
            ],
        )

    tem_carreta_dist = conn.execute(
        "SELECT COUNT(*) FROM faixas_distancia WHERE tipo_frete = 'Carreta Fechada'"
    ).fetchone()[0]
    if tem_carreta_dist == 0:
        conn.executemany(
            "INSERT INTO faixas_distancia (tipo_frete, de, ate, taxa_fixa, tarifa_km, observacao) VALUES (?,?,?,?,?,?)",
            [
                ("Carreta Fechada", 0, 200, 300.00, 4.50, "Carreta fechada — regional (exemplo, ajuste)"),
                ("Carreta Fechada", 200, 800, 500.00, 3.80, "Carreta fechada — interestadual (exemplo, ajuste)"),
                ("Carreta Fechada", 800, 999999, 900.00, 3.20, "Carreta fechada — longa distância (exemplo, ajuste)"),
            ],
        )


def init_db():
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        _migrar_colunas(conn)
        _seed_se_vazio(conn)
        _completar_carreta_fechada(conn)


def atualizar_coordenadas_filial(nome: str, latitude: float, longitude: float):
    with get_connection() as conn:
        conn.execute(
            "UPDATE filiais SET latitude = ?, longitude = ? WHERE nome = ?",
            (latitude, longitude, nome),
        )


def listar_filiais_admin() -> list[dict]:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM filiais ORDER BY nome")]


def inserir_filial(nome: str, endereco: str):
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO filiais (nome, endereco, latitude, longitude) VALUES (?,?,NULL,NULL)",
            (nome, endereco),
        )
        return cur.lastrowid


def atualizar_filial(id_: int, nome: str, endereco: str):
    # Sempre limpa latitude/longitude ao editar — o endereço pode ter
    # mudado, então força uma nova geocodificação na próxima vez que a
    # filial for usada num cálculo, em vez de ficar com coordenadas
    # desatualizadas em cache.
    with get_connection() as conn:
        conn.execute(
            "UPDATE filiais SET nome=?, endereco=?, latitude=NULL, longitude=NULL WHERE id=?",
            (nome, endereco, id_),
        )


def excluir_filial(id_: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM filiais WHERE id=?", (id_,))


def contar_filiais() -> int:
    with get_connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM filiais").fetchone()[0]


# ============================================================
# CRUD genérico para as tabelas de preço editáveis pela tela
# "Tabela de Preços". Cada função é explícita (não genérica por
# nome de tabela) para evitar SQL dinâmico a partir de entrada
# do usuário.
# ============================================================

def listar_faixas_peso() -> list[dict]:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM faixas_peso ORDER BY tipo_frete, de"
        )]


def inserir_faixa_peso(tipo_frete, de, ate, tarifa_base, custo_kg_adicional, observacao=""):
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO faixas_peso (tipo_frete, de, ate, tarifa_base, custo_kg_adicional, observacao) VALUES (?,?,?,?,?,?)",
            (tipo_frete, de, ate, tarifa_base, custo_kg_adicional, observacao),
        )
        return cur.lastrowid


def atualizar_faixa_peso(id_, tipo_frete, de, ate, tarifa_base, custo_kg_adicional, observacao=""):
    with get_connection() as conn:
        conn.execute(
            "UPDATE faixas_peso SET tipo_frete=?, de=?, ate=?, tarifa_base=?, custo_kg_adicional=?, observacao=? WHERE id=?",
            (tipo_frete, de, ate, tarifa_base, custo_kg_adicional, observacao, id_),
        )


def excluir_faixa_peso(id_):
    with get_connection() as conn:
        conn.execute("DELETE FROM faixas_peso WHERE id=?", (id_,))


def listar_faixas_distancia() -> list[dict]:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM faixas_distancia ORDER BY tipo_frete, de"
        )]


def inserir_faixa_distancia(tipo_frete, de, ate, taxa_fixa, tarifa_km, observacao=""):
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO faixas_distancia (tipo_frete, de, ate, taxa_fixa, tarifa_km, observacao) VALUES (?,?,?,?,?,?)",
            (tipo_frete, de, ate, taxa_fixa, tarifa_km, observacao),
        )
        return cur.lastrowid


def atualizar_faixa_distancia(id_, tipo_frete, de, ate, taxa_fixa, tarifa_km, observacao=""):
    with get_connection() as conn:
        conn.execute(
            "UPDATE faixas_distancia SET tipo_frete=?, de=?, ate=?, taxa_fixa=?, tarifa_km=?, observacao=? WHERE id=?",
            (tipo_frete, de, ate, taxa_fixa, tarifa_km, observacao, id_),
        )


def excluir_faixa_distancia(id_):
    with get_connection() as conn:
        conn.execute("DELETE FROM faixas_distancia WHERE id=?", (id_,))


def listar_faixas_coleta() -> list[dict]:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM faixas_coleta ORDER BY de")]


def inserir_faixa_coleta(de, ate, taxa_fixa, tarifa_km, observacao=""):
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO faixas_coleta (de, ate, taxa_fixa, tarifa_km, observacao) VALUES (?,?,?,?,?)",
            (de, ate, taxa_fixa, tarifa_km, observacao),
        )
        return cur.lastrowid


def atualizar_faixa_coleta(id_, de, ate, taxa_fixa, tarifa_km, observacao=""):
    with get_connection() as conn:
        conn.execute(
            "UPDATE faixas_coleta SET de=?, ate=?, taxa_fixa=?, tarifa_km=?, observacao=? WHERE id=?",
            (de, ate, taxa_fixa, tarifa_km, observacao, id_),
        )


def excluir_faixa_coleta(id_):
    with get_connection() as conn:
        conn.execute("DELETE FROM faixas_coleta WHERE id=?", (id_,))


def contar_faixas_coleta() -> int:
    with get_connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM faixas_coleta").fetchone()[0]


def listar_categorias_admin() -> list[dict]:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM categorias ORDER BY nome")]


def inserir_categoria(nome, multiplicador, observacao=""):
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO categorias (nome, multiplicador, observacao) VALUES (?,?,?)",
            (nome, multiplicador, observacao),
        )
        return cur.lastrowid


def atualizar_categoria(id_, nome, multiplicador, observacao=""):
    with get_connection() as conn:
        conn.execute(
            "UPDATE categorias SET nome=?, multiplicador=?, observacao=? WHERE id=?",
            (nome, multiplicador, observacao, id_),
        )


def excluir_categoria(id_):
    with get_connection() as conn:
        conn.execute("DELETE FROM categorias WHERE id=?", (id_,))


def contar_categorias() -> int:
    with get_connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM categorias").fetchone()[0]


def listar_transportes_admin() -> list[dict]:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM transportes ORDER BY nome")]


def inserir_transporte(nome, multiplicador, fator_cubagem, observacao=""):
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO transportes (nome, multiplicador, fator_cubagem, observacao) VALUES (?,?,?,?)",
            (nome, multiplicador, fator_cubagem, observacao),
        )
        return cur.lastrowid


def atualizar_transporte(id_, nome, multiplicador, fator_cubagem, observacao=""):
    with get_connection() as conn:
        conn.execute(
            "UPDATE transportes SET nome=?, multiplicador=?, fator_cubagem=?, observacao=? WHERE id=?",
            (nome, multiplicador, fator_cubagem, observacao, id_),
        )


def excluir_transporte(id_):
    with get_connection() as conn:
        conn.execute("DELETE FROM transportes WHERE id=?", (id_,))


def contar_transportes() -> int:
    with get_connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM transportes").fetchone()[0]


def listar_slas_admin() -> list[dict]:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM slas ORDER BY nome")]


def inserir_sla(nome, multiplicador, prazo_dias, observacao=""):
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO slas (nome, multiplicador, prazo_dias, observacao) VALUES (?,?,?,?)",
            (nome, multiplicador, prazo_dias, observacao),
        )
        return cur.lastrowid


def atualizar_sla(id_, nome, multiplicador, prazo_dias, observacao=""):
    with get_connection() as conn:
        conn.execute(
            "UPDATE slas SET nome=?, multiplicador=?, prazo_dias=?, observacao=? WHERE id=?",
            (nome, multiplicador, prazo_dias, observacao, id_),
        )


def excluir_sla(id_):
    with get_connection() as conn:
        conn.execute("DELETE FROM slas WHERE id=?", (id_,))


def contar_slas() -> int:
    with get_connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM slas").fetchone()[0]


def listar_veiculos_admin() -> list[dict]:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM veiculos ORDER BY nome")]


def inserir_veiculo(nome, de, ate, tarifa_km, peso_incluso_kg, valor_kg_excedente,
                     tarifa_km_retorno=0, tarifa_km_manutencao=0, capacidade_m3=0,
                     percentual_capacidade_util=80, observacao=""):
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO veiculos (nome, de, ate, tarifa_km, peso_incluso_kg, valor_kg_excedente, "
            "tarifa_km_retorno, tarifa_km_manutencao, capacidade_m3, percentual_capacidade_util, observacao) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (nome, de, ate, tarifa_km, peso_incluso_kg, valor_kg_excedente,
             tarifa_km_retorno, tarifa_km_manutencao, capacidade_m3, percentual_capacidade_util, observacao),
        )
        return cur.lastrowid


def atualizar_veiculo(id_, nome, de, ate, tarifa_km, peso_incluso_kg, valor_kg_excedente,
                       tarifa_km_retorno=0, tarifa_km_manutencao=0, capacidade_m3=0,
                       percentual_capacidade_util=80, observacao=""):
    with get_connection() as conn:
        conn.execute(
            "UPDATE veiculos SET nome=?, de=?, ate=?, tarifa_km=?, peso_incluso_kg=?, valor_kg_excedente=?, "
            "tarifa_km_retorno=?, tarifa_km_manutencao=?, capacidade_m3=?, percentual_capacidade_util=?, "
            "observacao=? WHERE id=?",
            (nome, de, ate, tarifa_km, peso_incluso_kg, valor_kg_excedente,
             tarifa_km_retorno, tarifa_km_manutencao, capacidade_m3, percentual_capacidade_util, observacao, id_),
        )


def excluir_veiculo(id_):
    with get_connection() as conn:
        conn.execute("DELETE FROM veiculos WHERE id=?", (id_,))


def contar_veiculos() -> int:
    with get_connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM veiculos").fetchone()[0]


def listar_taxas_adicionais_admin() -> list[dict]:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM taxas_adicionais ORDER BY nome")]


def inserir_taxa_adicional(nome, tipo, valor, observacao=""):
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO taxas_adicionais (nome, tipo, valor, observacao) VALUES (?,?,?,?)",
            (nome, tipo, valor, observacao),
        )
        return cur.lastrowid


def atualizar_taxa_adicional(id_, nome, tipo, valor, observacao=""):
    with get_connection() as conn:
        conn.execute(
            "UPDATE taxas_adicionais SET nome=?, tipo=?, valor=?, observacao=? WHERE id=?",
            (nome, tipo, valor, observacao, id_),
        )


def excluir_taxa_adicional(id_):
    with get_connection() as conn:
        conn.execute("DELETE FROM taxas_adicionais WHERE id=?", (id_,))


def listar_coleta_cidades_fixas_admin() -> list[dict]:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM coleta_cidades_fixas ORDER BY filial_origem, cidade_destino, veiculo"
        )]


def _dividir_cidades(texto: str) -> list[str]:
    """cidade_destino guarda uma ou mais cidades separadas por vírgula —
    ex: "Osasco, Barueri, Cotia" — essa função devolve a lista já sem
    espaços/entradas vazias. Uma cidade cadastrada sozinha (sem vírgula)
    vira naturalmente uma lista de 1."""
    return [c.strip() for c in (texto or "").split(",") if c.strip()]


def _cidades_coleta_conflitantes(
    conn: sqlite3.Connection, filial_origem: str, veiculo: str, cidades: list[str],
    ignorar_id: int | None = None,
) -> list[str]:
    """Cidades da lista que já aparecem em OUTRA linha do mesmo
    filial_origem+veiculo (comparação case-insensitive) — sem essa
    checagem, duas linhas cobrindo a mesma cidade tornariam ambíguo qual
    preço vale (buscar_coleta_cidade_fixa pegaria sempre a de id menor,
    silenciosamente)."""
    query = (
        "SELECT id, cidade_destino FROM coleta_cidades_fixas "
        "WHERE LOWER(filial_origem) = LOWER(?) AND LOWER(veiculo) = LOWER(?)"
    )
    params = [filial_origem.strip(), veiculo.strip()]
    if ignorar_id is not None:
        query += " AND id != ?"
        params.append(ignorar_id)
    alvo_lower = {c.lower() for c in cidades}
    # guarda a grafia já cadastrada na outra linha (não a do payload atual)
    # pra mensagem de erro apontar exatamente o que está no banco
    conflitos: dict[str, str] = {}
    for row in conn.execute(query, params):
        for cidade in _dividir_cidades(row["cidade_destino"]):
            if cidade.lower() in alvo_lower:
                conflitos[cidade.lower()] = cidade
    return sorted(conflitos.values())


def inserir_coleta_cidade_fixa(filial_origem, cidade_destino, veiculo, valor_fixo, observacao=""):
    cidades = _dividir_cidades(cidade_destino)
    if not cidades:
        raise sqlite3.IntegrityError("informe ao menos uma cidade do cliente")
    with get_connection() as conn:
        conflitos = _cidades_coleta_conflitantes(conn, filial_origem, veiculo, cidades)
        if conflitos:
            raise sqlite3.IntegrityError(
                f"cidade(s) {', '.join(conflitos)} já têm preço fixo de coleta cadastrado para "
                f"a filial '{filial_origem}' + veículo '{veiculo}' em outra linha"
            )
        cur = conn.execute(
            "INSERT INTO coleta_cidades_fixas (filial_origem, cidade_destino, veiculo, valor_fixo, observacao) "
            "VALUES (?,?,?,?,?)",
            (filial_origem, ", ".join(cidades), veiculo, valor_fixo, observacao),
        )
        return cur.lastrowid


def atualizar_coleta_cidade_fixa(id_, filial_origem, cidade_destino, veiculo, valor_fixo, observacao=""):
    cidades = _dividir_cidades(cidade_destino)
    if not cidades:
        raise sqlite3.IntegrityError("informe ao menos uma cidade do cliente")
    with get_connection() as conn:
        conflitos = _cidades_coleta_conflitantes(conn, filial_origem, veiculo, cidades, ignorar_id=id_)
        if conflitos:
            raise sqlite3.IntegrityError(
                f"cidade(s) {', '.join(conflitos)} já têm preço fixo de coleta cadastrado para "
                f"a filial '{filial_origem}' + veículo '{veiculo}' em outra linha"
            )
        conn.execute(
            "UPDATE coleta_cidades_fixas SET filial_origem=?, cidade_destino=?, veiculo=?, valor_fixo=?, observacao=? "
            "WHERE id=?",
            (filial_origem, ", ".join(cidades), veiculo, valor_fixo, observacao, id_),
        )


def excluir_coleta_cidade_fixa(id_):
    with get_connection() as conn:
        conn.execute("DELETE FROM coleta_cidades_fixas WHERE id=?", (id_,))


def buscar_coleta_cidade_fixa(filial_origem: str, cidade_destino: str, veiculo: str) -> dict | None:
    """Busca (case-insensitive) se a rota filial_origem -> cidade_destino,
    para o veículo informado, tem preço de coleta fixo cadastrado — a
    cidade pode estar em qualquer posição da lista guardada na linha."""
    alvo = cidade_destino.strip().lower()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM coleta_cidades_fixas "
            "WHERE LOWER(filial_origem) = LOWER(?) AND LOWER(veiculo) = LOWER(?) ORDER BY id",
            (filial_origem.strip(), veiculo.strip()),
        ).fetchall()
    for row in rows:
        if alvo in {c.lower() for c in _dividir_cidades(row["cidade_destino"])}:
            return dict(row)
    return None


def listar_transportadoras_terceirizadas_admin() -> list[dict]:
    with get_connection() as conn:
        return [
            dict(r) for r in conn.execute(
                "SELECT * FROM transportadoras_terceirizadas ORDER BY cidade, nome"
            )
        ]


def inserir_transportadora_terceirizada(nome, cidade, tipo, valor, observacao=""):
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO transportadoras_terceirizadas (nome, cidade, tipo, valor, observacao) VALUES (?,?,?,?,?)",
            (nome, cidade, tipo, valor, observacao),
        )
        return cur.lastrowid


def atualizar_transportadora_terceirizada(id_, nome, cidade, tipo, valor, observacao=""):
    with get_connection() as conn:
        conn.execute(
            "UPDATE transportadoras_terceirizadas SET nome=?, cidade=?, tipo=?, valor=?, observacao=? WHERE id=?",
            (nome, cidade, tipo, valor, observacao, id_),
        )


def excluir_transportadora_terceirizada(id_):
    with get_connection() as conn:
        conn.execute("DELETE FROM transportadoras_terceirizadas WHERE id=?", (id_,))


def listar_taxas_regionais_admin() -> list[dict]:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM taxas_regionais ORDER BY cidade, nome")]


def _taxa_regional_duplicada(conn: sqlite3.Connection, cidade: str, nome: str, ignorar_id: int | None = None) -> bool:
    """A UNIQUE(cidade, nome) é case-sensitive no SQLite, mas
    _taxas_regionais_aplicaveis (frete_service.py) compara em minúsculas —
    sem essa checagem, 'Manaus'/'MANAUS' com a mesma taxa cadastrada
    separadamente fariam a taxa ser aplicada em dobro no orçamento."""
    query = "SELECT 1 FROM taxas_regionais WHERE LOWER(cidade) = LOWER(?) AND LOWER(nome) = LOWER(?)"
    params = [cidade.strip(), nome.strip()]
    if ignorar_id is not None:
        query += " AND id != ?"
        params.append(ignorar_id)
    return conn.execute(query, params).fetchone() is not None


def inserir_taxa_regional(cidade, nome, tipo, valor, observacao=""):
    with get_connection() as conn:
        if _taxa_regional_duplicada(conn, cidade, nome):
            raise sqlite3.IntegrityError(f"taxa '{nome}' já cadastrada para a cidade '{cidade}'")
        cur = conn.execute(
            "INSERT INTO taxas_regionais (cidade, nome, tipo, valor, observacao) VALUES (?,?,?,?,?)",
            (cidade, nome, tipo, valor, observacao),
        )
        return cur.lastrowid


def atualizar_taxa_regional(id_, cidade, nome, tipo, valor, observacao=""):
    with get_connection() as conn:
        if _taxa_regional_duplicada(conn, cidade, nome, ignorar_id=id_):
            raise sqlite3.IntegrityError(f"taxa '{nome}' já cadastrada para a cidade '{cidade}'")
        conn.execute(
            "UPDATE taxas_regionais SET cidade=?, nome=?, tipo=?, valor=?, observacao=? WHERE id=?",
            (cidade, nome, tipo, valor, observacao, id_),
        )


def excluir_taxa_regional(id_):
    with get_connection() as conn:
        conn.execute("DELETE FROM taxas_regionais WHERE id=?", (id_,))


def listar_taxas_balsa_admin() -> list[dict]:
    with get_connection() as conn:
        return [
            dict(r) for r in conn.execute(
                "SELECT * FROM taxas_balsa ORDER BY cidade_origem, cidade_destino, veiculo"
            )
        ]


def _taxa_balsa_duplicada(
    conn: sqlite3.Connection, cidade_origem: str, cidade_destino: str, veiculo: str,
    ignorar_id: int | None = None,
) -> bool:
    """A UNIQUE(cidade_origem, cidade_destino, veiculo) é case-sensitive no
    SQLite, mas a aplicação no cálculo compara em minúsculas (ver
    frete_service._taxa_balsa_aplicavel) — sem essa checagem, duas linhas
    que só diferem em maiúsculas/minúsculas empatariam e a taxa aplicada
    dependeria da ordem de retorno do SQLite."""
    query = (
        "SELECT 1 FROM taxas_balsa WHERE LOWER(cidade_origem) = LOWER(?) AND LOWER(cidade_destino) = LOWER(?) "
        "AND LOWER(veiculo) = LOWER(?)"
    )
    params = [cidade_origem.strip(), cidade_destino.strip(), veiculo.strip()]
    if ignorar_id is not None:
        query += " AND id != ?"
        params.append(ignorar_id)
    return conn.execute(query, params).fetchone() is not None


def inserir_taxa_balsa(cidade_origem, cidade_destino, veiculo, tipo, valor, observacao=""):
    with get_connection() as conn:
        if _taxa_balsa_duplicada(conn, cidade_origem, cidade_destino, veiculo):
            raise sqlite3.IntegrityError(
                f"já existe uma taxa de balsa de '{cidade_origem}' → '{cidade_destino}' pro veículo '{veiculo}'"
            )
        cur = conn.execute(
            "INSERT INTO taxas_balsa (cidade_origem, cidade_destino, veiculo, tipo, valor, observacao) "
            "VALUES (?,?,?,?,?,?)",
            (cidade_origem, cidade_destino, veiculo, tipo, valor, observacao),
        )
        return cur.lastrowid


def atualizar_taxa_balsa(id_, cidade_origem, cidade_destino, veiculo, tipo, valor, observacao=""):
    with get_connection() as conn:
        if _taxa_balsa_duplicada(conn, cidade_origem, cidade_destino, veiculo, ignorar_id=id_):
            raise sqlite3.IntegrityError(
                f"já existe uma taxa de balsa de '{cidade_origem}' → '{cidade_destino}' pro veículo '{veiculo}'"
            )
        conn.execute(
            "UPDATE taxas_balsa SET cidade_origem=?, cidade_destino=?, veiculo=?, tipo=?, valor=?, observacao=? "
            "WHERE id=?",
            (cidade_origem, cidade_destino, veiculo, tipo, valor, observacao, id_),
        )


def excluir_taxa_balsa(id_):
    with get_connection() as conn:
        conn.execute("DELETE FROM taxas_balsa WHERE id=?", (id_,))


def _proximo_codigo_orcamento(conn: sqlite3.Connection) -> str:
    """Gera o próximo código sequencial (ORC-0001, ORC-0002...). Usa o
    maior número já usado (não a contagem de linhas), pra não repetir
    código se algum orçamento antigo for excluído do histórico."""
    row = conn.execute(
        "SELECT codigo FROM orcamentos_historico ORDER BY id DESC LIMIT 1"
    ).fetchone()
    proximo_num = 1
    if row and row["codigo"]:
        try:
            proximo_num = int(row["codigo"].split("-")[-1]) + 1
        except (ValueError, IndexError):
            pass
    return f"ORC-{proximo_num:04d}"


def salvar_orcamento_historico(
    cliente: str,
    responsavel: str,
    origem_resumo: str,
    destino_resumo: str,
    veiculo: str,
    distancia_km: float,
    valor_mercadoria: float,
    frete_total: float,
    dados_json: str,
    criado_por: str = "",
    status: str = "Fechado",
) -> dict:
    with get_connection() as conn:
        codigo = _proximo_codigo_orcamento(conn)
        criado_em = datetime.now().isoformat(timespec="seconds")
        conn.execute(
            """INSERT INTO orcamentos_historico
               (codigo, criado_em, cliente, responsavel, origem_resumo, destino_resumo,
                veiculo, distancia_km, valor_mercadoria, frete_total, status, dados_json, criado_por)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (codigo, criado_em, cliente, responsavel, origem_resumo, destino_resumo,
             veiculo, distancia_km, valor_mercadoria, frete_total, status, dados_json, criado_por),
        )
        return {"codigo": codigo, "criado_em": criado_em}


def listar_orcamentos_historico() -> list[dict]:
    with get_connection() as conn:
        return [
            dict(r) for r in conn.execute(
                "SELECT * FROM orcamentos_historico ORDER BY id DESC"
            )
        ]


def listar_rotas_historico() -> list[dict]:
    """Versão enxuta do histórico (sem dados_json) só com o que dá pra
    reaproveitar a distância de uma rota já cotada antes — ver
    geo_service._buscar_rota_no_historico, que evita chamar o serviço de
    geolocalização de novo quando a mesma rota (por cidade) E o mesmo
    veículo já foram cotados juntos antes (o pedágio pode variar por
    categoria de veículo, então precisa ser o mesmo veículo pra reaproveitar).
    Mais recentes primeiro, pra reaproveitar o dado mais atualizado quando
    a mesma rota+veículo tiver mais de uma cotação salva."""
    with get_connection() as conn:
        return [
            dict(r) for r in conn.execute(
                "SELECT origem_resumo, destino_resumo, veiculo, distancia_km "
                "FROM orcamentos_historico ORDER BY id DESC"
            )
        ]


def buscar_orcamento_historico(codigo: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM orcamentos_historico WHERE codigo = ?", (codigo,)
        ).fetchone()
        return dict(row) if row else None


def buscar_orcamento_historico_por_id(id_: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM orcamentos_historico WHERE id = ?", (id_,)
        ).fetchone()
        return dict(row) if row else None


def excluir_orcamento_historico(id_: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM orcamentos_historico WHERE id=?", (id_,))


# ============================================================
# Usuários e sessões (login) — as senhas nunca são retornadas
# pelas funções "_admin"; ver auth_service.py para hash/verificação.
# ============================================================

def _usuario_duplicado(conn: sqlite3.Connection, username: str, ignorar_id: int | None = None) -> bool:
    query = "SELECT 1 FROM usuarios WHERE LOWER(username) = LOWER(?)"
    params = [username.strip()]
    if ignorar_id is not None:
        query += " AND id != ?"
        params.append(ignorar_id)
    return conn.execute(query, params).fetchone() is not None


def listar_usuarios_admin() -> list[dict]:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id, nome, username, role, ativo, criado_em FROM usuarios ORDER BY nome"
        )]


def buscar_usuario_por_username(username: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM usuarios WHERE LOWER(username) = LOWER(?)", (username.strip(),)
        ).fetchone()
        return dict(row) if row else None


def buscar_usuario_por_id(id_: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM usuarios WHERE id = ?", (id_,)).fetchone()
        return dict(row) if row else None


def contar_usuarios() -> int:
    with get_connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]


def contar_admins_ativos(ignorar_id: int | None = None) -> int:
    """Usado para impedir que o último administrador ativo seja rebaixado,
    desativado ou excluído — o sistema sempre precisa de pelo menos um."""
    with get_connection() as conn:
        query = "SELECT COUNT(*) FROM usuarios WHERE role = 'admin' AND ativo = 1"
        params = []
        if ignorar_id is not None:
            query += " AND id != ?"
            params.append(ignorar_id)
        return conn.execute(query, params).fetchone()[0]


def inserir_usuario(nome: str, username: str, senha_hash: str, senha_salt: str, role: str, ativo: bool = True) -> int:
    with get_connection() as conn:
        if _usuario_duplicado(conn, username):
            raise sqlite3.IntegrityError(f"já existe um usuário com o login '{username}'")
        cur = conn.execute(
            "INSERT INTO usuarios (nome, username, senha_hash, senha_salt, role, ativo, criado_em) "
            "VALUES (?,?,?,?,?,?,?)",
            (nome, username, senha_hash, senha_salt, role, int(ativo), datetime.now().isoformat(timespec="seconds")),
        )
        return cur.lastrowid


def atualizar_usuario(id_: int, nome: str, username: str, role: str, ativo: bool):
    with get_connection() as conn:
        if _usuario_duplicado(conn, username, ignorar_id=id_):
            raise sqlite3.IntegrityError(f"já existe um usuário com o login '{username}'")
        conn.execute(
            "UPDATE usuarios SET nome=?, username=?, role=?, ativo=? WHERE id=?",
            (nome, username, role, int(ativo), id_),
        )


def atualizar_senha_usuario(id_: int, senha_hash: str, senha_salt: str):
    with get_connection() as conn:
        conn.execute(
            "UPDATE usuarios SET senha_hash=?, senha_salt=? WHERE id=?",
            (senha_hash, senha_salt, id_),
        )


def excluir_usuario(id_: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM usuarios WHERE id=?", (id_,))


def criar_sessao(token: str, usuario_id: int, criado_em: str, expira_em: str):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO sessoes (token, usuario_id, criado_em, expira_em) VALUES (?,?,?,?)",
            (token, usuario_id, criado_em, expira_em),
        )


def buscar_sessao(token: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT s.expira_em, u.id, u.nome, u.username, u.role, u.ativo "
            "FROM sessoes s JOIN usuarios u ON u.id = s.usuario_id WHERE s.token = ?",
            (token,),
        ).fetchone()
        return dict(row) if row else None


def excluir_sessao(token: str):
    with get_connection() as conn:
        conn.execute("DELETE FROM sessoes WHERE token=?", (token,))


def limpar_sessoes_expiradas(agora_iso: str):
    with get_connection() as conn:
        conn.execute("DELETE FROM sessoes WHERE expira_em < ?", (agora_iso,))