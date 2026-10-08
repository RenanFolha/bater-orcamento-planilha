# Desenvolvedor Chefe: RenanFolha

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

import csv
import io
import os
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import datetime

import db_conexao

DB_PATH = os.environ.get(
    "FRETE_DB_PATH",
    os.path.join(os.path.dirname(__file__), "frete.db"),
)

# Reexportada aqui por conveniência/compatibilidade: a maior parte do
# projeto (routers/*, deps.py, testes) importa só `frete_db as db` e
# espera `db.ConflitoIntegridade` -- ver db_conexao.py pro porquê dessa
# exceção existir (substitui sqlite3.IntegrityError agora que o banco
# pode não ser SQLite).
ConflitoIntegridade = db_conexao.ConflitoIntegridade


def normalizar_texto(texto: str) -> str:
    """minúsculas + sem acento + sem espaço nas pontas — usado para
    comparar nome de filial/cidade cadastrado em lugares independentes
    (ex: nome da filial vs. cidade digitada numa taxa de balsa/regional)
    sem que uma diferença de acentuação (ex: 'Belem' vs 'Belém') faça a
    comparação falhar silenciosamente. LOWER() do SQLite não remove
    acento, por isso normaliza em Python."""
    sem_acento = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode("ascii")
    return sem_acento.strip().lower()

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
    -- UF onde a filial fica -- o endereço cadastrado normalmente é só rua/
    -- número/bairro/CEP (o nome da filial já funciona como "cidade de
    -- referência", ver comentário na tela de admin), sem cidade/UF no
    -- texto, então não dá pra extrair a UF dele (ver
    -- frete_service._uf_de_origem_ou_destino). Usado pelo cálculo de ICMS
    -- quando a origem/destino do frete é uma filial.
    uf TEXT NOT NULL DEFAULT '',
    latitude REAL,
    longitude REAL
);

CREATE TABLE IF NOT EXISTS veiculos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL UNIQUE,
    de REAL NOT NULL DEFAULT 0,
    ate REAL NOT NULL DEFAULT 999999,
    tarifa_km REAL NOT NULL,
    valor_tonelada_excedente REAL NOT NULL DEFAULT 0,
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

CREATE TABLE IF NOT EXISTS faixas_km_veiculo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Quando o veículo tem faixas cadastradas aqui, o R$/km escalonado
    -- por distância substitui o tarifa_km fixo do veículo (ver
    -- frete_service._tarifa_km_efetiva) — veículo sem nenhuma faixa
    -- continua usando o tarifa_km fixo normalmente.
    veiculo TEXT NOT NULL,
    de REAL NOT NULL,
    ate REAL NOT NULL,
    tarifa_km REAL NOT NULL,
    observacao TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS taxas_adicionais (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL UNIQUE,
    tipo TEXT NOT NULL DEFAULT 'fixo' CHECK (tipo IN ('fixo', 'percentual')),
    valor REAL NOT NULL DEFAULT 0,
    observacao TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS custos_lotacao_destino (
    -- Custo operacional (R$) de uma rota de lotação (FTL) fechada,
    -- porta-a-porta, por origem cadastrada (ex: "AM" = filial Manaus) e
    -- cidade/UF de destino -- substitui tarifa_km*distância quando a
    -- rota está cadastrada aqui (ver frete_service.calcular_orcamento /
    -- _custo_lotacao_destino_aplicavel), já que os valores vêm de uma
    -- tabela de custo pré-negociada por rota (a mesma lógica da planilha
    -- legada "TB LOTAÇÃO - CUSTO"), não de uma tarifa por km. Sem rota
    -- cadastrada, cai no fallback de tarifa_km*distância normal.
    -- cidade_destino_norm é a chave de busca (sem acento, minúscula,
    -- ver normalizar_texto) -- cidade_destino guarda a grafia original
    -- só para exibição/edição.
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    origem_tabela TEXT NOT NULL,
    uf_destino TEXT NOT NULL,
    cidade_destino TEXT NOT NULL,
    cidade_destino_norm TEXT NOT NULL,
    custo_total REAL NOT NULL,
    observacao TEXT DEFAULT '',
    UNIQUE(origem_tabela, uf_destino, cidade_destino_norm)
);

CREATE TABLE IF NOT EXISTS custos_fracionado_destino (
    -- Custo operacional (R$) do Fracionado (LTL) por faixa de peso,
    -- componente (coleta/embarque/entrega) e destino -- mesma lógica de
    -- custos_lotacao_destino (tabela pré-negociada, não fórmula por km),
    -- só que o Fracionado tem 3 componentes de custo e cada um escala
    -- por faixa de peso (ver frete_service._custo_fracionado_destino_
    -- aplicavel): v10..v200 são o custo total até aquele limite de peso
    -- (kg), excedente_kg é o R$/kg adicional acima de 200kg -- extraído
    -- das abas "TB FRACIONADO - CUSTO (SP/AM)" da planilha legada.
    -- capital_interior guarda o texto exato da planilha ('CAPITAL',
    -- 'INTERIOR', ou no caso da Bahia 'INTERIOR I'/'INTERIOR II').
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    origem_tabela TEXT NOT NULL,
    uf_destino TEXT NOT NULL,
    capital_interior TEXT NOT NULL,
    componente TEXT NOT NULL CHECK (componente IN ('coleta', 'embarque', 'entrega')),
    v10 REAL NOT NULL,
    v20 REAL NOT NULL,
    v30 REAL NOT NULL,
    v50 REAL NOT NULL,
    v70 REAL NOT NULL,
    v100 REAL NOT NULL,
    v150 REAL NOT NULL,
    v200 REAL NOT NULL,
    excedente_kg REAL NOT NULL,
    UNIQUE(origem_tabela, uf_destino, capital_interior, componente)
);

CREATE TABLE IF NOT EXISTS prazo_fracionado_destino (
    -- Prazo estimado (dias úteis) do Fracionado (LTL) por destino --
    -- diferente da Lotação (FTL), o prazo real do Fracionado não varia
    -- com km rodado (dados reais da planilha legada não mostram
    -- correlação alguma com distância), varia com a classificação do
    -- destino (UF + capital/interior) -- ver
    -- _prazo_fracionado_destino_aplicavel. dias_uteis é a moda (valor
    -- mais frequente) observada em cotações reais pra essa combinação
    -- origem+destino; sem rota cadastrada aqui, calcular_orcamento_
    -- fracionado cai no fallback de _prazo_estimado_dias_uteis (fórmula
    -- por km, validada só pra Lotação).
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    origem_tabela TEXT NOT NULL,
    uf_destino TEXT NOT NULL,
    capital_interior TEXT NOT NULL,
    dias_uteis INTEGER NOT NULL,
    UNIQUE(origem_tabela, uf_destino, capital_interior)
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
    observacao TEXT DEFAULT '',
    UNIQUE(nome, cidade)
);

CREATE TABLE IF NOT EXISTS taxas_regionais (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Uma ou mais cidades separadas por vírgula (mesmo padrão de
    -- coleta_cidades_fixas.cidade_destino) — uma taxa só cobre várias
    -- cidades ao mesmo tempo, sem precisar de uma linha por cidade. Sem
    -- UNIQUE aqui de propósito: a checagem de cidade duplicada (mesma
    -- cidade em duas linhas da mesma taxa) é feita em Python (ver
    -- _cidades_regionais_conflitantes).
    cidade TEXT NOT NULL,
    nome TEXT NOT NULL,
    tipo TEXT NOT NULL DEFAULT 'fixo' CHECK (tipo IN ('fixo', 'percentual')),
    valor REAL NOT NULL,
    observacao TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS taxas_balsa (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Direcional de propósito (cidade_origem -> cidade_destino): o preço da
    -- travessia pode ser diferente na ida e na volta, então cada linha só
    -- vale naquela direção específica — cadastre 2 linhas se ida e volta
    -- tiverem valores diferentes. O valor também pode mudar por veículo
    -- (balsa cobra por categoria do veículo embarcado). cidade_origem,
    -- cidade_destino e veiculo aceitam "*" como curinga (ver
    -- frete_service._taxa_balsa_aplicavel) — usado pra modelar corredor
    -- fluvial (ex: "*" -> "Manaus" vale de qualquer origem); quando mais
    -- de uma linha bate na mesma rota, vence a mais específica.
    cidade_origem TEXT NOT NULL,
    cidade_destino TEXT NOT NULL,
    veiculo TEXT NOT NULL,
    tipo TEXT NOT NULL DEFAULT 'fixo' CHECK (tipo IN ('fixo', 'percentual')),
    valor REAL NOT NULL,
    observacao TEXT DEFAULT '',
    UNIQUE(cidade_origem, cidade_destino, veiculo)
);

CREATE TABLE IF NOT EXISTS taxas_diaria_veiculo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Diária de carreta + cavalo cobrada UMA VEZ por orçamento quando há
    -- retirada OU entrega no cliente com frota própria (não terceirizada)
    -- numa UF cadastrada aqui — ex: parada em Manaus/AM pra embarque em
    -- balsa. UF (sigla) é a chave, sem curinga "*" (diferente das outras
    -- tabelas de taxa): cada estado com diária só pode ter uma linha (ver
    -- frete_service._diaria_veiculo_aplicada).
    uf TEXT NOT NULL UNIQUE,
    valor_carreta REAL NOT NULL,
    valor_cavalo REAL NOT NULL,
    observacao TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS prioridades_rota (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Regra de roteirização: quando a rota bate estado_origem (UF) ->
    -- cidade_destino, a distância do frete deixa de ser calculada direto e
    -- passa a ser a soma de origem -> filial_escala + filial_escala ->
    -- destino (ex: Manaus não tem acesso rodoviário direto da maioria dos
    -- estados -- a carga sempre passa por uma filial em Belém antes de
    -- seguir de balsa). estado_origem e cidade_destino aceitam "*" como
    -- curinga (mesmo mecanismo de taxas_balsa, ver
    -- frete_service.prioridade_rota_aplicavel); quando mais de uma
    -- linha bate na mesma rota, vence a mais específica.
    estado_origem TEXT NOT NULL,
    cidade_destino TEXT NOT NULL,
    filial_escala TEXT NOT NULL,
    observacao TEXT DEFAULT '',
    UNIQUE(estado_origem, cidade_destino)
);

CREATE TABLE IF NOT EXISTS aliquotas_icms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Matriz de alíquotas de ICMS por UF de origem -> UF de destino,
    -- aplicada "por dentro" (gross-up) sobre o frete_total já calculado
    -- (com a margem de lucro embutida), somado por último, depois do
    -- PIS/COFINS: frete_com_icms = frete_total / (1 - aliquota/100)
    -- (ver frete_service.aliquota_icms_aplicavel e _aplicar_icms).
    -- estado_origem e estado_destino aceitam "*" como curinga (mesmo
    -- mecanismo de taxas_balsa/prioridades_rota) -- quando mais de uma
    -- linha bate na mesma rota, vence a mais específica.
    estado_origem TEXT NOT NULL,
    estado_destino TEXT NOT NULL,
    aliquota REAL NOT NULL,
    observacao TEXT DEFAULT '',
    UNIQUE(estado_origem, estado_destino)
);

CREATE TABLE IF NOT EXISTS aliquota_pis_cofins (
    -- Alíquota federal única de PIS/COFINS (não varia por UF, diferente
    -- do ICMS) -- percentual simples somado sobre o frete_total ANTES da
    -- margem de lucro e do ICMS (ver frete_service.calcular_orcamento). Tabela
    -- singleton: sempre tem exatamente 1 linha (id=1), editada por
    -- UPDATE em vez de INSERT/DELETE (ver atualizar_aliquota_pis_cofins).
    id INTEGER PRIMARY KEY CHECK (id = 1),
    aliquota REAL NOT NULL,
    observacao TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS pracas_pedagio (
    -- Catálogo de praças de pedágio, com preço por número de eixos do
    -- veículo (padrão real das tabelas publicadas pelas concessionárias
    -- de rodovia) -- ver frete_service.pedagio_rota_aplicavel. UNIQUE
    -- em (nome, rodovia) porque o mesmo nome de praça pode se repetir
    -- em rodovias diferentes, mas não duas vezes na mesma rodovia (é
    -- usado como chave de upsert no import CSV, ver
    -- importar_pracas_pedagio_csv).
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    rodovia TEXT NOT NULL,
    concessionaria TEXT NOT NULL,
    uf TEXT NOT NULL DEFAULT '',
    km TEXT NOT NULL DEFAULT '',
    valor_eixo_2 REAL NOT NULL DEFAULT 0,
    valor_eixo_3 REAL NOT NULL DEFAULT 0,
    valor_eixo_4 REAL NOT NULL DEFAULT 0,
    valor_eixo_5 REAL NOT NULL DEFAULT 0,
    valor_eixo_6 REAL NOT NULL DEFAULT 0,
    valor_eixo_7 REAL NOT NULL DEFAULT 0,
    valor_eixo_8 REAL NOT NULL DEFAULT 0,
    valor_eixo_9 REAL NOT NULL DEFAULT 0,
    observacao TEXT DEFAULT '',
    UNIQUE(nome, rodovia)
);

CREATE TABLE IF NOT EXISTS pedagios_rota (
    -- Liga um corredor (cidade_origem -> cidade_destino, direcional,
    -- mesmo mecanismo de curinga "*" de taxas_balsa) às praças de
    -- pracas_pedagio que aquela rota atravessa. Uma rota pode ter várias
    -- linhas (uma por praça) -- o valor final é a SOMA de todas as
    -- praças do corredor mais específico que bater (ver
    -- frete_service.pedagio_rota_aplicavel), diferente de taxas_balsa
    -- que escolhe só uma linha vencedora.
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cidade_origem TEXT NOT NULL,
    cidade_destino TEXT NOT NULL,
    praca_id INTEGER NOT NULL REFERENCES pracas_pedagio(id),
    observacao TEXT DEFAULT '',
    UNIQUE(cidade_origem, cidade_destino, praca_id)
);

CREATE TABLE IF NOT EXISTS distancias_fixas (
    -- Sobrepõe o cálculo automático de distância (rodoviário via OSRM/
    -- Google) pra um corredor cidade_origem -> cidade_destino, direcional
    -- (mesmo mecanismo de curinga "*" e especificidade de taxas_balsa).
    -- Existe pra corredores onde a rota real usada na prática (ex: com
    -- travessia de balsa) é bem diferente da rota 100% rodoviária que o
    -- serviço de mapa calcula (ver geo_service._rota_ou_fixa) -- ex:
    -- Belém -> Manaus: rodoviário puro dá uma volta enorme (~3000km+)
    -- porque a BR-319 não é confiável, mas a rota real com balsa é bem
    -- mais curta. Vale tanto pra rota direta quanto pra cada perna de
    -- uma "Prioridade de Rota" (escala obrigatória via filial).
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cidade_origem TEXT NOT NULL,
    cidade_destino TEXT NOT NULL,
    distancia_km REAL NOT NULL,
    observacao TEXT DEFAULT '',
    UNIQUE(cidade_origem, cidade_destino)
);

CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    username TEXT NOT NULL UNIQUE,
    senha_hash TEXT NOT NULL,
    senha_salt TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'usuario' CHECK (role IN ('admin', 'usuario')),
    ativo INTEGER NOT NULL DEFAULT 1,
    criado_em TEXT NOT NULL DEFAULT '',
    deve_trocar_senha INTEGER NOT NULL DEFAULT 0
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

CREATE TABLE IF NOT EXISTS orcamentos_historico_alteracoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    historico_id INTEGER NOT NULL REFERENCES orcamentos_historico(id) ON DELETE CASCADE,
    campo TEXT NOT NULL,
    valor_antigo REAL,
    valor_novo REAL,
    alterado_por TEXT NOT NULL DEFAULT '',
    alterado_em TEXT NOT NULL
);
"""


@contextmanager
def get_connection():
    # DB_PATH é passado explicitamente como default aqui (em vez de
    # db_conexao.py ter sua própria cópia do caminho) justamente pra
    # preservar o monkeypatch de DB_PATH que os testes usam (ver
    # tests/conftest.py::banco_temporario) -- só entra em jogo quando o
    # tipo configurado é "sqlite" e db_config.json não sobrescreveu o
    # caminho (o caso de sempre, pra quem nunca abriu a tela "Banco de
    # dados").
    conn = db_conexao.conectar(sqlite_path_padrao=DB_PATH)
    try:
        yield conn
        conn.commit()
    except db_conexao.ERROS_INTEGRIDADE_NATIVOS as exc:
        conn.rollback()
        raise db_conexao.ConflitoIntegridade(str(exc)) from exc
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
                ("Rodoviário", 1.00, 300, "Padrão para cargas nacionais"),
                ("Aéreo", 2.50, 167, "Mais rápido e mais caro")
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
            "INSERT INTO veiculos (nome, de, ate, tarifa_km, valor_tonelada_excedente, capacidade_m3, observacao) VALUES (?,?,?,?,?,?,?)",
            [
                ("Caminhonete", 0, 750, 2.00, 1.50, 2.5, "Valores de exemplo — ajuste na Tabela de Preços"),
                ("Van / HR", 750, 1500, 2.60, 1.10, 8.0, "Valores de exemplo — ajuste"),
                ("VUC", 1500, 3500, 3.20, 0.80, 15.0, "Valores de exemplo — ajuste"),
                ("Truck / Toco (Caminhão 3/4)", 3500, 8000, 4.80, 0.45, 35.0, "Valores de exemplo — ajuste"),
                ("Carreta", 8000, 999999, 5.50, 0.35, 90.0, "Valores de exemplo — ajuste"),
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

    _seed_aliquotas_icms_interestadual(conn)

    if conn.execute("SELECT COUNT(*) FROM aliquota_pis_cofins").fetchone()[0] == 0:
        conn.execute(
            "INSERT INTO aliquota_pis_cofins (id, aliquota, observacao) VALUES (1, ?, ?)",
            (9.25, "Regime não-cumulativo (PIS 1,65% + COFINS 7,6%) — ajuste conforme o regime tributário da empresa"),
        )

    if conn.execute("SELECT COUNT(*) FROM taxas_diaria_veiculo").fetchone()[0] == 0:
        conn.execute(
            "INSERT INTO taxas_diaria_veiculo (uf, valor_carreta, valor_cavalo, observacao) VALUES (?,?,?,?)",
            ("AM", 220.00, 819.00, "Diária cobrada uma vez por orçamento quando há retirada ou entrega no cliente com frota própria em Manaus/AM"),
        )


# UFs do Sul e do Sudeste, exceto o Espírito Santo -- de acordo com a
# Resolução do Senado Federal nº 22/1989, quem vende a partir desses 6
# estados cobra 7% de ICMS em QUALQUER venda interestadual (pra qualquer
# outro UF); os outros 21 estados cobram 12% em qualquer venda
# interestadual. Confirmado contra a tabela de referência "ICMS.jpeg" na
# raiz do projeto -- usada também pra pegar a alíquota interna (mesmo
# estado) de cada UF abaixo.
_UF_SUL_SUDESTE_MENOS_ES = {"SP", "RJ", "MG", "PR", "SC", "RS"}

# Alíquota interna (ICMS dentro do mesmo estado, não interestadual) de
# cada UF -- fonte: tabela de referência "ICMS.jpeg" na raiz do projeto.
_ALIQUOTA_ICMS_INTERNA_POR_UF = {
    "AC": 17.0, "AL": 17.0, "AM": 18.0, "AP": 18.0, "BA": 18.0, "CE": 17.0,
    "DF": 18.0, "ES": 17.0, "GO": 17.0, "MA": 18.0, "MT": 17.0, "MS": 18.0,
    "MG": 18.0, "PA": 17.0, "PB": 18.0, "PR": 18.0, "PE": 18.0, "PI": 17.0,
    "RN": 18.0, "RS": 18.0, "RJ": 19.0, "RO": 17.0, "RR": 17.0, "SC": 17.0,
    "SP": 18.0, "SE": 18.0, "TO": 18.0,
}

def _seed_aliquotas_icms_interestadual(conn: sqlite3.Connection):
    """Popula a matriz de ICMS só na primeira vez que a tabela
    aliquotas_icms existir vazia (não sobrescreve o que já foi
    cadastrado/editado) -- uma linha "origem -> *" por UF com a alíquota
    interestadual (7% pras 6 UFs do Sul/Sudeste exceto ES, 12% pras
    outras 21, pra qualquer destino) mais uma linha "origem -> própria UF"
    com a alíquota interna de cada estado — mais específica, então vence a
    genérica "-> *" quando origem e destino calculados forem a mesma UF
    (ver especificidade em frete_service.aliquota_icms_aplicavel). Fonte:
    tabela de referência "ICMS.jpeg" na raiz do projeto.

    É só um ponto de partida: a alíquota efetiva real pode variar por NCM
    e regime tributário do destinatário (Simples Nacional, contribuinte ou
    não) e substituição tributária/DIFAL. Revise com a contabilidade antes
    de usar pra cobrar cliente de verdade."""
    if conn.execute("SELECT COUNT(*) FROM aliquotas_icms").fetchone()[0] > 0:
        return
    obs_interestadual = "Alíquota interestadual (Resolução do Senado 22/1989), fonte: tabela ICMS.jpeg do projeto — revisar exceções por NCM/regime tributário"
    obs_interna = "Alíquota interna (mesmo estado), fonte: tabela ICMS.jpeg do projeto — revisar exceções por NCM/regime tributário"
    linhas = []
    for uf, aliquota_interna in _ALIQUOTA_ICMS_INTERNA_POR_UF.items():
        aliquota_interestadual = 7.0 if uf in _UF_SUL_SUDESTE_MENOS_ES else 12.0
        linhas.append((uf, "*", aliquota_interestadual, obs_interestadual))
        linhas.append((uf, uf, aliquota_interna, obs_interna))
    conn.executemany(
        "INSERT INTO aliquotas_icms (estado_origem, estado_destino, aliquota, observacao) VALUES (?,?,?,?)",
        linhas,
    )


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


def _migrar_taxas_regionais_lista(conn: sqlite3.Connection):
    """taxas_regionais passou a aceitar uma LISTA de cidades separadas por
    vírgula em `cidade` (mesmo motivo de coleta_cidades_fixas — uma taxa
    cobre várias cidades numa linha só). Remove a antiga UNIQUE(cidade,
    nome) recriando a tabela e preservando todas as linhas e ids."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='taxas_regionais'"
    ).fetchone()
    if not row or "UNIQUE(cidade, nome)" not in (row["sql"] or ""):
        return  # já migrado
    conn.execute("ALTER TABLE taxas_regionais RENAME TO taxas_regionais_old")
    conn.execute("""
        CREATE TABLE taxas_regionais (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cidade TEXT NOT NULL,
            nome TEXT NOT NULL,
            tipo TEXT NOT NULL DEFAULT 'fixo' CHECK (tipo IN ('fixo', 'percentual')),
            valor REAL NOT NULL,
            observacao TEXT DEFAULT ''
        )
    """)
    conn.execute("""
        INSERT INTO taxas_regionais (id, cidade, nome, tipo, valor, observacao)
        SELECT id, cidade, nome, tipo, valor, observacao FROM taxas_regionais_old
    """)
    conn.execute("DROP TABLE taxas_regionais_old")


def _migrar_transportadoras_terceirizadas_unique(conn: sqlite3.Connection):
    """transportadoras_terceirizadas não tinha nenhuma constraint UNIQUE
    (nome+cidade podiam se repetir sem erro, mesmo a mensagem de conflito
    do router prometendo o contrário — ver
    routers/admin_precos.py:admin_criar_transportadora_terceirizada).
    Adiciona UNIQUE(nome, cidade), recriando a tabela (SQLite não tem
    ALTER TABLE ADD CONSTRAINT). Linhas com nome+cidade duplicados: fica
    a de menor id (INSERT OR IGNORE, ordenado por id) — se isso
    acontecer, quem cadastrou precisa conferir manualmente qual valor
    prevaleceu."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='transportadoras_terceirizadas'"
    ).fetchone()
    if not row or "UNIQUE(nome, cidade)" in (row["sql"] or ""):
        return  # tabela nova (já criada com a constraint) ou já migrada
    conn.execute("ALTER TABLE transportadoras_terceirizadas RENAME TO transportadoras_terceirizadas_old")
    conn.execute("""
        CREATE TABLE transportadoras_terceirizadas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            cidade TEXT NOT NULL,
            tipo TEXT NOT NULL DEFAULT 'ambos' CHECK (tipo IN ('coleta', 'entrega', 'ambos')),
            valor REAL NOT NULL,
            observacao TEXT DEFAULT '',
            UNIQUE(nome, cidade)
        )
    """)
    conn.execute("""
        INSERT OR IGNORE INTO transportadoras_terceirizadas (id, nome, cidade, tipo, valor, observacao)
        SELECT id, nome, cidade, tipo, valor, observacao FROM transportadoras_terceirizadas_old ORDER BY id
    """)
    conn.execute("DROP TABLE transportadoras_terceirizadas_old")


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
    _migrar_taxas_regionais_lista(conn)
    _migrar_transportadoras_terceirizadas_unique(conn)
    if not _coluna_existe(conn, "filiais", "uf"):
        conn.execute("ALTER TABLE filiais ADD COLUMN uf TEXT NOT NULL DEFAULT ''")
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
    if not _coluna_existe(conn, "veiculos", "numero_eixos"):
        # Usado pra achar o preço certo nas praças de pedágio cadastradas
        # (pracas_pedagio.valor_eixo_N) -- 0 = não cadastrado, o veículo
        # fica de fora do cálculo automático de pedágio até ser preenchido
        # (ver frete_service.pedagio_rota_aplicavel).
        conn.execute("ALTER TABLE veiculos ADD COLUMN numero_eixos INTEGER NOT NULL DEFAULT 0")
    if not _coluna_existe(conn, "orcamentos_historico", "criado_por"):
        # Registra qual conta de login efetivamente salvou o registro —
        # distinto de "responsavel" (texto livre, quem o usuário diz ser o
        # responsável pelo orçamento). Usado só para controlar quem pode
        # excluir o registro (dono ou admin), sem mudar o campo visível
        # "Responsável" que já existia. Bancos antigos ficam com '' (só
        # admin consegue excluir esses registros legados).
        conn.execute("ALTER TABLE orcamentos_historico ADD COLUMN criado_por TEXT NOT NULL DEFAULT ''")
    if _coluna_existe(conn, "veiculos", "peso_incluso_kg"):
        # Franquia de peso removida do cálculo — o excedente agora é só
        # o que passa do "até" do próprio veículo, sem campo de franquia
        # separado (ver frete_service.calcular_orcamento).
        # DROP COLUMN existe desde o SQLite 3.35 (2021).
        conn.execute("ALTER TABLE veiculos DROP COLUMN peso_incluso_kg")
    if _coluna_existe(conn, "veiculos", "valor_kg_excedente"):
        # Renomeado: o valor cadastrado é por TONELADA excedente, não
        # por kg — o nome antigo (valor_kg_excedente) induzia a cadastrar
        # um valor 1000x maior que o pretendido.
        # RENAME COLUMN existe desde o SQLite 3.25 (2018).
        conn.execute("ALTER TABLE veiculos RENAME COLUMN valor_kg_excedente TO valor_tonelada_excedente")
    if not _coluna_existe(conn, "usuarios", "deve_trocar_senha"):
        # Sinaliza que o usuário precisa trocar a senha no próximo login —
        # usado pra obrigar a troca da senha padrão do admin criado
        # automaticamente (ver garantir_usuario_padrao em auth_service.py).
        conn.execute("ALTER TABLE usuarios ADD COLUMN deve_trocar_senha INTEGER NOT NULL DEFAULT 0")
    if _coluna_existe(conn, "escalas_obrigatorias", "cidade_origem"):
        # Campo original era cidade de origem exata -- trocado por UF
        # (estado_origem), porque a regra de roteirização normalmente vale
        # pro estado inteiro, não só pra uma cidade específica.
        # RENAME COLUMN existe desde o SQLite 3.25 (2018).
        conn.execute("ALTER TABLE escalas_obrigatorias RENAME COLUMN cidade_origem TO estado_origem")
    if _coluna_existe(conn, "escalas_obrigatorias", "estado_origem"):
        # Tabela renomeada de escalas_obrigatorias pra prioridades_rota
        # (nome mais claro pro usuário) -- prioridades_rota já foi criada
        # vazia pelo schema acima, então migra as linhas que existirem e
        # descarta a tabela antiga.
        conn.execute(
            "INSERT INTO prioridades_rota (estado_origem, cidade_destino, filial_escala, observacao) "
            "SELECT estado_origem, cidade_destino, filial_escala, observacao FROM escalas_obrigatorias"
        )
        conn.execute("DROP TABLE escalas_obrigatorias")


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


_PK_DDL_POR_DIALETO = {
    "sqlserver": "INT IDENTITY(1,1) PRIMARY KEY",
    "mysql": "INT AUTO_INCREMENT PRIMARY KEY",
    "postgresql": "SERIAL PRIMARY KEY",
}

# Schema "final" (já com todas as colunas que hoje só existem no SQLite
# por causa de ALTER TABLE incremental, ver _migrar_colunas) pros três
# dialetos não-SQLite -- um servidor novo nasce direto nesse formato,
# nunca precisa repetir a cadeia histórica de migração incremental (essa
# só existe pra não quebrar quem já tinha um frete.db de uma versão
# anterior). Colunas que entram em UNIQUE/PRIMARY KEY usam VARCHAR(255)
# em vez de TEXT porque o MySQL não aceita TEXT/BLOB em índice sem
# tamanho de prefixo -- as demais (livres, sem constraint) continuam
# TEXT, compatível nos três dialetos.
SCHEMA_CONSOLIDADO_TEMPLATE = """
CREATE TABLE faixas_peso (
    id {PK},
    tipo_frete VARCHAR(60) NOT NULL DEFAULT 'Fracionado',
    de REAL NOT NULL,
    ate REAL NOT NULL,
    tarifa_base REAL NOT NULL,
    custo_kg_adicional REAL NOT NULL DEFAULT 0,
    observacao TEXT DEFAULT ''
);

CREATE TABLE faixas_distancia (
    id {PK},
    tipo_frete VARCHAR(60) NOT NULL DEFAULT 'Fracionado',
    de REAL NOT NULL,
    ate REAL NOT NULL,
    taxa_fixa REAL NOT NULL,
    tarifa_km REAL NOT NULL DEFAULT 0,
    observacao TEXT DEFAULT ''
);

CREATE TABLE faixas_coleta (
    id {PK},
    de REAL NOT NULL,
    ate REAL NOT NULL,
    taxa_fixa REAL NOT NULL,
    tarifa_km REAL NOT NULL DEFAULT 0,
    observacao TEXT DEFAULT ''
);

CREATE TABLE categorias (
    id {PK},
    nome VARCHAR(255) NOT NULL UNIQUE,
    multiplicador REAL NOT NULL,
    observacao TEXT DEFAULT ''
);

CREATE TABLE transportes (
    id {PK},
    nome VARCHAR(255) NOT NULL UNIQUE,
    multiplicador REAL NOT NULL,
    fator_cubagem REAL NOT NULL,
    observacao TEXT DEFAULT ''
);

CREATE TABLE slas (
    id {PK},
    nome VARCHAR(255) NOT NULL UNIQUE,
    multiplicador REAL NOT NULL,
    prazo_dias INTEGER NOT NULL,
    observacao TEXT DEFAULT ''
);

CREATE TABLE filiais (
    id {PK},
    nome VARCHAR(255) NOT NULL UNIQUE,
    endereco TEXT NOT NULL,
    uf VARCHAR(10) NOT NULL DEFAULT '',
    latitude REAL,
    longitude REAL
);

CREATE TABLE veiculos (
    id {PK},
    nome VARCHAR(255) NOT NULL UNIQUE,
    de REAL NOT NULL DEFAULT 0,
    ate REAL NOT NULL DEFAULT 999999,
    tarifa_km REAL NOT NULL,
    valor_tonelada_excedente REAL NOT NULL DEFAULT 0,
    tarifa_km_retorno REAL NOT NULL DEFAULT 0,
    tarifa_km_manutencao REAL NOT NULL DEFAULT 0,
    capacidade_m3 REAL NOT NULL DEFAULT 0,
    percentual_capacidade_util REAL NOT NULL DEFAULT 80,
    numero_eixos INTEGER NOT NULL DEFAULT 0,
    observacao TEXT DEFAULT ''
);

CREATE TABLE faixas_km_veiculo (
    id {PK},
    veiculo TEXT NOT NULL,
    de REAL NOT NULL,
    ate REAL NOT NULL,
    tarifa_km REAL NOT NULL,
    observacao TEXT DEFAULT ''
);

CREATE TABLE taxas_adicionais (
    id {PK},
    nome VARCHAR(255) NOT NULL UNIQUE,
    tipo VARCHAR(20) NOT NULL DEFAULT 'fixo' CHECK (tipo IN ('fixo', 'percentual')),
    valor REAL NOT NULL DEFAULT 0,
    observacao TEXT DEFAULT ''
);

CREATE TABLE custos_lotacao_destino (
    id {PK},
    origem_tabela VARCHAR(60) NOT NULL,
    uf_destino VARCHAR(10) NOT NULL,
    cidade_destino TEXT NOT NULL,
    cidade_destino_norm VARCHAR(255) NOT NULL,
    custo_total REAL NOT NULL,
    observacao TEXT DEFAULT '',
    UNIQUE(origem_tabela, uf_destino, cidade_destino_norm)
);

CREATE TABLE custos_fracionado_destino (
    id {PK},
    origem_tabela VARCHAR(60) NOT NULL,
    uf_destino VARCHAR(10) NOT NULL,
    capital_interior VARCHAR(20) NOT NULL,
    componente VARCHAR(20) NOT NULL CHECK (componente IN ('coleta', 'embarque', 'entrega')),
    v10 REAL NOT NULL,
    v20 REAL NOT NULL,
    v30 REAL NOT NULL,
    v50 REAL NOT NULL,
    v70 REAL NOT NULL,
    v100 REAL NOT NULL,
    v150 REAL NOT NULL,
    v200 REAL NOT NULL,
    excedente_kg REAL NOT NULL,
    UNIQUE(origem_tabela, uf_destino, capital_interior, componente)
);

CREATE TABLE prazo_fracionado_destino (
    id {PK},
    origem_tabela VARCHAR(60) NOT NULL,
    uf_destino VARCHAR(10) NOT NULL,
    capital_interior VARCHAR(20) NOT NULL,
    dias_uteis INTEGER NOT NULL,
    UNIQUE(origem_tabela, uf_destino, capital_interior)
);

CREATE TABLE coleta_cidades_fixas (
    id {PK},
    filial_origem TEXT NOT NULL,
    cidade_destino TEXT NOT NULL,
    veiculo TEXT NOT NULL,
    valor_fixo REAL NOT NULL,
    observacao TEXT DEFAULT ''
);

CREATE TABLE transportadoras_terceirizadas (
    id {PK},
    nome VARCHAR(255) NOT NULL,
    cidade VARCHAR(255) NOT NULL,
    tipo VARCHAR(20) NOT NULL DEFAULT 'ambos' CHECK (tipo IN ('coleta', 'entrega', 'ambos')),
    valor REAL NOT NULL,
    observacao TEXT DEFAULT '',
    UNIQUE(nome, cidade)
);

CREATE TABLE taxas_regionais (
    id {PK},
    cidade TEXT NOT NULL,
    nome TEXT NOT NULL,
    tipo VARCHAR(20) NOT NULL DEFAULT 'fixo' CHECK (tipo IN ('fixo', 'percentual')),
    valor REAL NOT NULL,
    observacao TEXT DEFAULT ''
);

CREATE TABLE taxas_balsa (
    id {PK},
    cidade_origem VARCHAR(255) NOT NULL,
    cidade_destino VARCHAR(255) NOT NULL,
    veiculo VARCHAR(255) NOT NULL,
    tipo VARCHAR(20) NOT NULL DEFAULT 'fixo' CHECK (tipo IN ('fixo', 'percentual')),
    valor REAL NOT NULL,
    observacao TEXT DEFAULT '',
    UNIQUE(cidade_origem, cidade_destino, veiculo)
);

CREATE TABLE taxas_diaria_veiculo (
    id {PK},
    uf VARCHAR(10) NOT NULL UNIQUE,
    valor_carreta REAL NOT NULL,
    valor_cavalo REAL NOT NULL,
    observacao TEXT DEFAULT ''
);

CREATE TABLE prioridades_rota (
    id {PK},
    estado_origem VARCHAR(255) NOT NULL,
    cidade_destino VARCHAR(255) NOT NULL,
    filial_escala TEXT NOT NULL,
    observacao TEXT DEFAULT '',
    UNIQUE(estado_origem, cidade_destino)
);

CREATE TABLE aliquotas_icms (
    id {PK},
    estado_origem VARCHAR(10) NOT NULL,
    estado_destino VARCHAR(10) NOT NULL,
    aliquota REAL NOT NULL,
    observacao TEXT DEFAULT '',
    UNIQUE(estado_origem, estado_destino)
);

CREATE TABLE aliquota_pis_cofins (
    id INT PRIMARY KEY,
    aliquota REAL NOT NULL,
    observacao TEXT DEFAULT ''
);

CREATE TABLE pracas_pedagio (
    id {PK},
    nome VARCHAR(255) NOT NULL,
    rodovia VARCHAR(255) NOT NULL,
    concessionaria TEXT NOT NULL,
    uf VARCHAR(10) NOT NULL DEFAULT '',
    km VARCHAR(50) NOT NULL DEFAULT '',
    valor_eixo_2 REAL NOT NULL DEFAULT 0,
    valor_eixo_3 REAL NOT NULL DEFAULT 0,
    valor_eixo_4 REAL NOT NULL DEFAULT 0,
    valor_eixo_5 REAL NOT NULL DEFAULT 0,
    valor_eixo_6 REAL NOT NULL DEFAULT 0,
    valor_eixo_7 REAL NOT NULL DEFAULT 0,
    valor_eixo_8 REAL NOT NULL DEFAULT 0,
    valor_eixo_9 REAL NOT NULL DEFAULT 0,
    observacao TEXT DEFAULT '',
    UNIQUE(nome, rodovia)
);

CREATE TABLE pedagios_rota (
    id {PK},
    cidade_origem VARCHAR(255) NOT NULL,
    cidade_destino VARCHAR(255) NOT NULL,
    praca_id INTEGER NOT NULL REFERENCES pracas_pedagio(id),
    observacao TEXT DEFAULT '',
    UNIQUE(cidade_origem, cidade_destino, praca_id)
);

CREATE TABLE distancias_fixas (
    id {PK},
    cidade_origem VARCHAR(255) NOT NULL,
    cidade_destino VARCHAR(255) NOT NULL,
    distancia_km REAL NOT NULL,
    observacao TEXT DEFAULT '',
    UNIQUE(cidade_origem, cidade_destino)
);

CREATE TABLE usuarios (
    id {PK},
    nome TEXT NOT NULL,
    username VARCHAR(255) NOT NULL UNIQUE,
    senha_hash TEXT NOT NULL,
    senha_salt TEXT NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'usuario' CHECK (role IN ('admin', 'usuario')),
    ativo INTEGER NOT NULL DEFAULT 1,
    criado_em TEXT NOT NULL DEFAULT '',
    deve_trocar_senha INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE sessoes (
    token VARCHAR(255) PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    criado_em TEXT NOT NULL,
    expira_em TEXT NOT NULL
);

CREATE TABLE orcamentos_historico (
    id {PK},
    codigo VARCHAR(255) NOT NULL UNIQUE,
    criado_em TEXT NOT NULL,
    cliente TEXT NOT NULL DEFAULT '',
    responsavel TEXT NOT NULL DEFAULT '',
    origem_resumo TEXT DEFAULT '',
    destino_resumo TEXT DEFAULT '',
    veiculo TEXT DEFAULT '',
    distancia_km REAL DEFAULT 0,
    valor_mercadoria REAL DEFAULT 0,
    frete_total REAL DEFAULT 0,
    status VARCHAR(30) NOT NULL DEFAULT 'Fechado',
    dados_json TEXT NOT NULL DEFAULT '{}',
    criado_por TEXT NOT NULL DEFAULT ''
);

CREATE TABLE orcamentos_historico_alteracoes (
    id {PK},
    historico_id INTEGER NOT NULL REFERENCES orcamentos_historico(id) ON DELETE CASCADE,
    campo VARCHAR(255) NOT NULL,
    valor_antigo REAL,
    valor_novo REAL,
    alterado_por VARCHAR(255) NOT NULL DEFAULT '',
    alterado_em TEXT NOT NULL
);
"""


def _gerar_schema_consolidado(tipo: str) -> str:
    """Monta o DDL de criação das tabelas pro dialeto pedido (sqlserver/
    mysql/postgresql — SQLite continua usando SCHEMA + _migrar_colunas,
    sem passar por aqui). Usado só na primeira vez que um banco externo
    é configurado (ver POST /admin/banco-dados/aplicar em
    routers/admin_banco.py) -- o destino sempre nasce do zero, direto no
    formato final, sem precisar da cadeia histórica de ALTER TABLE que o
    SQLite acumulou ao longo do tempo."""
    return SCHEMA_CONSOLIDADO_TEMPLATE.replace("{PK}", _PK_DDL_POR_DIALETO[tipo])


def init_db():
    tipo = db_conexao.carregar_config().get("tipo", "sqlite")
    with get_connection() as conn:
        if tipo == "sqlite":
            conn.executescript(SCHEMA)
            _migrar_colunas(conn)
        else:
            conn.executescript(_gerar_schema_consolidado(tipo))
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


def inserir_filial(nome: str, endereco: str, uf: str = ""):
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO filiais (nome, endereco, uf, latitude, longitude) VALUES (?,?,?,NULL,NULL)",
            (nome, endereco, uf),
        )
        return cur.lastrowid


def atualizar_filial(id_: int, nome: str, endereco: str, uf: str = ""):
    # Sempre limpa latitude/longitude ao editar — o endereço pode ter
    # mudado, então força uma nova geocodificação na próxima vez que a
    # filial for usada num cálculo, em vez de ficar com coordenadas
    # desatualizadas em cache.
    with get_connection() as conn:
        conn.execute(
            "UPDATE filiais SET nome=?, endereco=?, uf=?, latitude=NULL, longitude=NULL WHERE id=?",
            (nome, endereco, uf, id_),
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


def contar_faixas_peso_fracionado() -> int:
    with get_connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM faixas_peso WHERE tipo_frete = 'Fracionado'").fetchone()[0]


def contar_faixas_distancia_fracionado() -> int:
    with get_connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM faixas_distancia WHERE tipo_frete = 'Fracionado'").fetchone()[0]


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


def listar_faixas_km_veiculo_admin() -> list[dict]:
    with get_connection() as conn:
        return [
            dict(r) for r in conn.execute(
                "SELECT * FROM faixas_km_veiculo ORDER BY veiculo, de"
            )
        ]


def inserir_faixa_km_veiculo(veiculo, de, ate, tarifa_km, observacao=""):
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO faixas_km_veiculo (veiculo, de, ate, tarifa_km, observacao) VALUES (?,?,?,?,?)",
            (veiculo, de, ate, tarifa_km, observacao),
        )
        return cur.lastrowid


def atualizar_faixa_km_veiculo(id_, veiculo, de, ate, tarifa_km, observacao=""):
    with get_connection() as conn:
        conn.execute(
            "UPDATE faixas_km_veiculo SET veiculo=?, de=?, ate=?, tarifa_km=?, observacao=? WHERE id=?",
            (veiculo, de, ate, tarifa_km, observacao, id_),
        )


def excluir_faixa_km_veiculo(id_):
    with get_connection() as conn:
        conn.execute("DELETE FROM faixas_km_veiculo WHERE id=?", (id_,))


def listar_veiculos_admin() -> list[dict]:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM veiculos ORDER BY nome")]


def inserir_veiculo(nome, de, ate, tarifa_km, valor_tonelada_excedente,
                     tarifa_km_retorno=0, tarifa_km_manutencao=0, capacidade_m3=0,
                     percentual_capacidade_util=80, numero_eixos=0, observacao=""):
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO veiculos (nome, de, ate, tarifa_km, valor_tonelada_excedente, "
            "tarifa_km_retorno, tarifa_km_manutencao, capacidade_m3, percentual_capacidade_util, "
            "numero_eixos, observacao) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (nome, de, ate, tarifa_km, valor_tonelada_excedente,
             tarifa_km_retorno, tarifa_km_manutencao, capacidade_m3, percentual_capacidade_util,
             numero_eixos, observacao),
        )
        return cur.lastrowid


def atualizar_veiculo(id_, nome, de, ate, tarifa_km, valor_tonelada_excedente,
                       tarifa_km_retorno=0, tarifa_km_manutencao=0, capacidade_m3=0,
                       percentual_capacidade_util=80, numero_eixos=0, observacao=""):
    with get_connection() as conn:
        conn.execute(
            "UPDATE veiculos SET nome=?, de=?, ate=?, tarifa_km=?, valor_tonelada_excedente=?, "
            "tarifa_km_retorno=?, tarifa_km_manutencao=?, capacidade_m3=?, percentual_capacidade_util=?, "
            "numero_eixos=?, observacao=? WHERE id=?",
            (nome, de, ate, tarifa_km, valor_tonelada_excedente,
             tarifa_km_retorno, tarifa_km_manutencao, capacidade_m3, percentual_capacidade_util,
             numero_eixos, observacao, id_),
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


def _cidades_em_conflito(
    conn: sqlite3.Connection, query: str, params: list, coluna_cidades: str, cidades: list[str],
) -> list[str]:
    """Cidades da lista que já aparecem em alguma linha retornada por
    `query`/`params` (comparação case-insensitive) — helper compartilhado
    pelas checagens de duplicidade de coleta_cidades_fixas e
    taxas_regionais, que só diferem na query (chave de agrupamento) e na
    coluna que guarda a lista de cidades separadas por vírgula. Guarda a
    grafia já cadastrada na outra linha (não a do payload atual) pra
    mensagem de erro apontar exatamente o que está no banco."""
    alvo_lower = {c.lower() for c in cidades}
    conflitos: dict[str, str] = {}
    for row in conn.execute(query, params):
        for cidade in _dividir_cidades(row[coluna_cidades]):
            if cidade.lower() in alvo_lower:
                conflitos[cidade.lower()] = cidade
    return sorted(conflitos.values())


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
    return _cidades_em_conflito(conn, query, params, "cidade_destino", cidades)


def inserir_coleta_cidade_fixa(filial_origem, cidade_destino, veiculo, valor_fixo, observacao=""):
    cidades = _dividir_cidades(cidade_destino)
    if not cidades:
        raise db_conexao.ConflitoIntegridade("informe ao menos uma cidade do cliente")
    with get_connection() as conn:
        conflitos = _cidades_coleta_conflitantes(conn, filial_origem, veiculo, cidades)
        if conflitos:
            raise db_conexao.ConflitoIntegridade(
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
        raise db_conexao.ConflitoIntegridade("informe ao menos uma cidade do cliente")
    with get_connection() as conn:
        conflitos = _cidades_coleta_conflitantes(conn, filial_origem, veiculo, cidades, ignorar_id=id_)
        if conflitos:
            raise db_conexao.ConflitoIntegridade(
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
    """Busca se a rota filial_origem -> cidade_destino, para o veículo
    informado, tem preço de coleta fixo cadastrado — a cidade pode estar
    em qualquer posição da lista guardada na linha. Comparação por
    normalizar_texto (sem acento/case) em vez de LOWER() do SQL, que não
    remove acento — filial_origem e cidade_destino vêm de cadastros
    independentes (nome da filial vs. texto digitado na taxa), então uma
    grafia diferente (ex: 'Belem' vs 'Belém') não pode quebrar o match."""
    filial_alvo = normalizar_texto(filial_origem)
    veic_alvo = normalizar_texto(veiculo)
    alvo = normalizar_texto(cidade_destino)
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM coleta_cidades_fixas ORDER BY id").fetchall()
    for row in rows:
        if normalizar_texto(row["filial_origem"]) != filial_alvo or normalizar_texto(row["veiculo"]) != veic_alvo:
            continue
        if alvo in {normalizar_texto(c) for c in _dividir_cidades(row["cidade_destino"])}:
            return dict(row)
    return None


def buscar_coleta_cidade_fixa_outros_veiculos(filial_origem: str, cidade_destino: str, veiculo_atual: str) -> list[str]:
    """Veículos (diferentes do informado) que têm preço fixo de coleta
    cadastrado pra essa mesma filial+cidade — usado só como diagnóstico
    (ver frete_service.calcular_orcamento) quando o preço fixo quase
    bateu, mas não pro veículo escolhido no orçamento: em vez de cair
    silenciosamente pra faixa por km, a memória de cálculo avisa que
    havia preço fixo pra outro(s) veículo(s)."""
    filial_alvo = normalizar_texto(filial_origem)
    alvo = normalizar_texto(cidade_destino)
    veic_atual = normalizar_texto(veiculo_atual)
    with get_connection() as conn:
        rows = conn.execute("SELECT veiculo, filial_origem, cidade_destino FROM coleta_cidades_fixas").fetchall()
    encontrados = set()
    for row in rows:
        if normalizar_texto(row["filial_origem"]) != filial_alvo:
            continue
        if normalizar_texto(row["veiculo"]) == veic_atual:
            continue
        if alvo in {normalizar_texto(c) for c in _dividir_cidades(row["cidade_destino"])}:
            encontrados.add(row["veiculo"])
    return sorted(encontrados)


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


def _cidades_regionais_conflitantes(
    conn: sqlite3.Connection, nome: str, cidades: list[str], ignorar_id: int | None = None,
) -> list[str]:
    """Cidades da lista que já aparecem em OUTRA linha da mesma taxa
    (mesmo `nome`, case-insensitive) — sem essa checagem, duas linhas
    cobrindo a mesma cidade fariam a taxa ser aplicada em dobro no
    orçamento (_taxas_regionais_aplicaveis soma todas as que baterem)."""
    query = "SELECT id, cidade FROM taxas_regionais WHERE LOWER(nome) = LOWER(?)"
    params = [nome.strip()]
    if ignorar_id is not None:
        query += " AND id != ?"
        params.append(ignorar_id)
    return _cidades_em_conflito(conn, query, params, "cidade", cidades)


def inserir_taxa_regional(cidade, nome, tipo, valor, observacao=""):
    cidades = _dividir_cidades(cidade)
    if not cidades:
        raise db_conexao.ConflitoIntegridade("informe ao menos uma cidade")
    with get_connection() as conn:
        conflitos = _cidades_regionais_conflitantes(conn, nome, cidades)
        if conflitos:
            raise db_conexao.ConflitoIntegridade(
                f"cidade(s) {', '.join(conflitos)} já têm a taxa '{nome}' cadastrada em outra linha"
            )
        cur = conn.execute(
            "INSERT INTO taxas_regionais (cidade, nome, tipo, valor, observacao) VALUES (?,?,?,?,?)",
            (", ".join(cidades), nome, tipo, valor, observacao),
        )
        return cur.lastrowid


def atualizar_taxa_regional(id_, cidade, nome, tipo, valor, observacao=""):
    cidades = _dividir_cidades(cidade)
    if not cidades:
        raise db_conexao.ConflitoIntegridade("informe ao menos uma cidade")
    with get_connection() as conn:
        conflitos = _cidades_regionais_conflitantes(conn, nome, cidades, ignorar_id=id_)
        if conflitos:
            raise db_conexao.ConflitoIntegridade(
                f"cidade(s) {', '.join(conflitos)} já têm a taxa '{nome}' cadastrada em outra linha"
            )
        conn.execute(
            "UPDATE taxas_regionais SET cidade=?, nome=?, tipo=?, valor=?, observacao=? WHERE id=?",
            (", ".join(cidades), nome, tipo, valor, observacao, id_),
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


def _existe_duplicata(
    conn: sqlite3.Connection, tabela: str, campos_lower: dict[str, str],
    campos_exatos: dict[str, object] | None = None, ignorar_id: int | None = None,
) -> bool:
    """Checa se já existe uma linha em `tabela` cujos campos batem com os
    valores dados -- `campos_lower` compara case-insensitive (LOWER(campo)
    = LOWER(?), valor já stripado antes de chamar) e `campos_exatos`
    compara igualdade direta (ex: praca_id, que é inteiro, não texto).
    `ignorar_id` exclui a própria linha (edição). `tabela` nunca vem de
    entrada do usuário -- só de uma string fixa no código de cada chamador
    (mesmo padrão de db_conexao.exportar_todas_tabelas).

    Helper compartilhado pelas checagens de duplicidade de taxas_balsa,
    prioridades_rota, aliquotas_icms, pracas_pedagio, pedagios_rota,
    distancias_fixas e usuarios -- a UNIQUE nativa do SQLite é
    case-sensitive, mas a aplicação sempre compara em minúsculas (ver as
    funções `*_aplicavel` de frete_service.py)."""
    condicoes = [f"LOWER({campo}) = LOWER(?)" for campo in campos_lower]
    params = list(campos_lower.values())
    if campos_exatos:
        condicoes += [f"{campo} = ?" for campo in campos_exatos]
        params += list(campos_exatos.values())
    query = f"SELECT 1 FROM {tabela} WHERE " + " AND ".join(condicoes)
    if ignorar_id is not None:
        query += " AND id != ?"
        params.append(ignorar_id)
    return conn.execute(query, params).fetchone() is not None


def _taxa_balsa_duplicada(
    conn: sqlite3.Connection, cidade_origem: str, cidade_destino: str, veiculo: str,
    ignorar_id: int | None = None,
) -> bool:
    return _existe_duplicata(
        conn, "taxas_balsa",
        {"cidade_origem": cidade_origem.strip(), "cidade_destino": cidade_destino.strip(), "veiculo": veiculo.strip()},
        ignorar_id=ignorar_id,
    )


def inserir_taxa_balsa(cidade_origem, cidade_destino, veiculo, tipo, valor, observacao=""):
    with get_connection() as conn:
        if _taxa_balsa_duplicada(conn, cidade_origem, cidade_destino, veiculo):
            raise db_conexao.ConflitoIntegridade(
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
            raise db_conexao.ConflitoIntegridade(
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


def listar_prioridades_rota_admin() -> list[dict]:
    with get_connection() as conn:
        return [
            dict(r) for r in conn.execute(
                "SELECT * FROM prioridades_rota ORDER BY estado_origem, cidade_destino"
            )
        ]


def _prioridade_rota_duplicada(
    conn: sqlite3.Connection, estado_origem: str, cidade_destino: str, ignorar_id: int | None = None,
) -> bool:
    return _existe_duplicata(
        conn, "prioridades_rota",
        {"estado_origem": estado_origem.strip(), "cidade_destino": cidade_destino.strip()},
        ignorar_id=ignorar_id,
    )


def inserir_prioridade_rota(estado_origem, cidade_destino, filial_escala, observacao=""):
    with get_connection() as conn:
        if _prioridade_rota_duplicada(conn, estado_origem, cidade_destino):
            raise db_conexao.ConflitoIntegridade(
                f"já existe uma prioridade de rota de '{estado_origem}' → '{cidade_destino}'"
            )
        cur = conn.execute(
            "INSERT INTO prioridades_rota (estado_origem, cidade_destino, filial_escala, observacao) "
            "VALUES (?,?,?,?)",
            (estado_origem, cidade_destino, filial_escala, observacao),
        )
        return cur.lastrowid


def atualizar_prioridade_rota(id_, estado_origem, cidade_destino, filial_escala, observacao=""):
    with get_connection() as conn:
        if _prioridade_rota_duplicada(conn, estado_origem, cidade_destino, ignorar_id=id_):
            raise db_conexao.ConflitoIntegridade(
                f"já existe uma prioridade de rota de '{estado_origem}' → '{cidade_destino}'"
            )
        conn.execute(
            "UPDATE prioridades_rota SET estado_origem=?, cidade_destino=?, filial_escala=?, observacao=? "
            "WHERE id=?",
            (estado_origem, cidade_destino, filial_escala, observacao, id_),
        )


def excluir_prioridade_rota(id_):
    with get_connection() as conn:
        conn.execute("DELETE FROM prioridades_rota WHERE id=?", (id_,))


def listar_aliquotas_icms_admin() -> list[dict]:
    with get_connection() as conn:
        return [
            dict(r) for r in conn.execute(
                "SELECT * FROM aliquotas_icms ORDER BY estado_origem, estado_destino"
            )
        ]


def _aliquota_icms_duplicada(
    conn: sqlite3.Connection, estado_origem: str, estado_destino: str, ignorar_id: int | None = None,
) -> bool:
    return _existe_duplicata(
        conn, "aliquotas_icms",
        {"estado_origem": estado_origem.strip(), "estado_destino": estado_destino.strip()},
        ignorar_id=ignorar_id,
    )


def inserir_aliquota_icms(estado_origem, estado_destino, aliquota, observacao=""):
    with get_connection() as conn:
        if _aliquota_icms_duplicada(conn, estado_origem, estado_destino):
            raise db_conexao.ConflitoIntegridade(
                f"já existe uma alíquota de ICMS cadastrada de '{estado_origem}' → '{estado_destino}'"
            )
        cur = conn.execute(
            "INSERT INTO aliquotas_icms (estado_origem, estado_destino, aliquota, observacao) "
            "VALUES (?,?,?,?)",
            (estado_origem, estado_destino, aliquota, observacao),
        )
        return cur.lastrowid


def atualizar_aliquota_icms(id_, estado_origem, estado_destino, aliquota, observacao=""):
    with get_connection() as conn:
        if _aliquota_icms_duplicada(conn, estado_origem, estado_destino, ignorar_id=id_):
            raise db_conexao.ConflitoIntegridade(
                f"já existe uma alíquota de ICMS cadastrada de '{estado_origem}' → '{estado_destino}'"
            )
        conn.execute(
            "UPDATE aliquotas_icms SET estado_origem=?, estado_destino=?, aliquota=?, observacao=? WHERE id=?",
            (estado_origem, estado_destino, aliquota, observacao, id_),
        )


def excluir_aliquota_icms(id_):
    with get_connection() as conn:
        conn.execute("DELETE FROM aliquotas_icms WHERE id=?", (id_,))


def listar_custos_lotacao_destino(origem_tabela: str | None = None) -> list[dict]:
    with get_connection() as conn:
        if origem_tabela:
            rows = conn.execute(
                "SELECT * FROM custos_lotacao_destino WHERE origem_tabela = ? ORDER BY uf_destino, cidade_destino",
                (origem_tabela,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM custos_lotacao_destino ORDER BY origem_tabela, uf_destino, cidade_destino"
            ).fetchall()
        return [dict(r) for r in rows]


def importar_custos_lotacao_destino(origem_tabela: str, linhas: list[dict]) -> dict:
    """Upsert em lote por (origem_tabela, uf_destino, cidade_destino_norm)
    -- cada item de `linhas` é um dict com 'cidade', 'uf', 'custo_total' e
    opcionalmente 'observacao'. Usado para popular a tabela a partir dos
    dados extraídos da planilha legada (ver scripts de extração), não
    tem endpoint de API/tela ainda -- ver frete_service.calcular_orcamento
    para como o valor é usado."""
    criadas, atualizadas = 0, 0
    with get_connection() as conn:
        for linha in linhas:
            cidade, uf, custo_total = linha["cidade"], linha["uf"].strip().upper(), linha["custo_total"]
            cidade_norm = normalizar_texto(cidade)
            observacao = linha.get("observacao", "")
            existente = conn.execute(
                "SELECT id FROM custos_lotacao_destino WHERE origem_tabela=? AND uf_destino=? AND cidade_destino_norm=?",
                (origem_tabela, uf, cidade_norm),
            ).fetchone()
            if existente:
                conn.execute(
                    "UPDATE custos_lotacao_destino SET cidade_destino=?, custo_total=?, observacao=? WHERE id=?",
                    (cidade, custo_total, observacao, existente["id"]),
                )
                atualizadas += 1
            else:
                conn.execute(
                    "INSERT INTO custos_lotacao_destino "
                    "(origem_tabela, uf_destino, cidade_destino, cidade_destino_norm, custo_total, observacao) "
                    "VALUES (?,?,?,?,?,?)",
                    (origem_tabela, uf, cidade, cidade_norm, custo_total, observacao),
                )
                criadas += 1
    return {"criadas": criadas, "atualizadas": atualizadas}


def listar_custos_fracionado_destino(origem_tabela: str | None = None) -> list[dict]:
    with get_connection() as conn:
        if origem_tabela:
            rows = conn.execute(
                "SELECT * FROM custos_fracionado_destino WHERE origem_tabela = ? "
                "ORDER BY uf_destino, capital_interior, componente",
                (origem_tabela,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM custos_fracionado_destino "
                "ORDER BY origem_tabela, uf_destino, capital_interior, componente"
            ).fetchall()
        return [dict(r) for r in rows]


def importar_custos_fracionado_destino(origem_tabela: str, linhas: list[dict]) -> dict:
    """Upsert em lote por (origem_tabela, uf_destino, capital_interior,
    componente) -- cada item de `linhas` é um dict com 'uf',
    'capital_interior', 'componente' e os valores de faixa de peso
    ('v10','v20','v30','v50','v70','v100','v150','v200','excedente_kg').
    Usado para popular a tabela a partir dos dados extraídos da planilha
    legada (abas "TB FRACIONADO - CUSTO (SP/AM)"), não tem endpoint de
    API/tela ainda -- ver frete_service._custo_fracionado_destino_aplicavel
    para como o valor é usado."""
    criadas, atualizadas = 0, 0
    campos_faixa = ("v10", "v20", "v30", "v50", "v70", "v100", "v150", "v200", "excedente_kg")
    with get_connection() as conn:
        for linha in linhas:
            uf = linha["uf"].strip().upper()
            capital_interior = linha["capital_interior"].strip().upper()
            componente = linha["componente"].strip().lower()
            valores = [linha[campo] for campo in campos_faixa]
            existente = conn.execute(
                "SELECT id FROM custos_fracionado_destino "
                "WHERE origem_tabela=? AND uf_destino=? AND capital_interior=? AND componente=?",
                (origem_tabela, uf, capital_interior, componente),
            ).fetchone()
            if existente:
                conn.execute(
                    f"UPDATE custos_fracionado_destino SET {', '.join(c + '=?' for c in campos_faixa)} "
                    "WHERE id=?",
                    (*valores, existente["id"]),
                )
                atualizadas += 1
            else:
                conn.execute(
                    "INSERT INTO custos_fracionado_destino "
                    "(origem_tabela, uf_destino, capital_interior, componente, "
                    f"{', '.join(campos_faixa)}) VALUES (?,?,?,?,{','.join(['?'] * len(campos_faixa))})",
                    (origem_tabela, uf, capital_interior, componente, *valores),
                )
                criadas += 1
    return {"criadas": criadas, "atualizadas": atualizadas}


def listar_prazo_fracionado_destino(origem_tabela: str | None = None) -> list[dict]:
    with get_connection() as conn:
        if origem_tabela:
            rows = conn.execute(
                "SELECT * FROM prazo_fracionado_destino WHERE origem_tabela = ? "
                "ORDER BY uf_destino, capital_interior",
                (origem_tabela,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM prazo_fracionado_destino ORDER BY origem_tabela, uf_destino, capital_interior"
            ).fetchall()
        return [dict(r) for r in rows]


def importar_prazo_fracionado_destino(origem_tabela: str, linhas: list[dict]) -> dict:
    """Upsert em lote por (origem_tabela, uf_destino, capital_interior) --
    cada item de `linhas` é um dict com 'uf', 'capital_interior' e
    'dias_uteis'. Usado para popular a tabela a partir da moda observada
    em cotações reais da planilha legada (ver investigação documentada em
    CONTEXTO.md), não tem endpoint de API/tela ainda -- ver
    frete_service._prazo_fracionado_destino_aplicavel para como o valor é
    usado."""
    criadas, atualizadas = 0, 0
    with get_connection() as conn:
        for linha in linhas:
            uf = linha["uf"].strip().upper()
            capital_interior = linha["capital_interior"].strip().upper()
            dias_uteis = int(linha["dias_uteis"])
            existente = conn.execute(
                "SELECT id FROM prazo_fracionado_destino "
                "WHERE origem_tabela=? AND uf_destino=? AND capital_interior=?",
                (origem_tabela, uf, capital_interior),
            ).fetchone()
            if existente:
                conn.execute(
                    "UPDATE prazo_fracionado_destino SET dias_uteis=? WHERE id=?",
                    (dias_uteis, existente["id"]),
                )
                atualizadas += 1
            else:
                conn.execute(
                    "INSERT INTO prazo_fracionado_destino "
                    "(origem_tabela, uf_destino, capital_interior, dias_uteis) VALUES (?,?,?,?)",
                    (origem_tabela, uf, capital_interior, dias_uteis),
                )
                criadas += 1
    return {"criadas": criadas, "atualizadas": atualizadas}


def obter_aliquota_pis_cofins() -> dict:
    with get_connection() as conn:
        return dict(conn.execute("SELECT * FROM aliquota_pis_cofins WHERE id = 1").fetchone())


def atualizar_aliquota_pis_cofins(aliquota: float, observacao: str = ""):
    with get_connection() as conn:
        conn.execute(
            "UPDATE aliquota_pis_cofins SET aliquota=?, observacao=? WHERE id = 1",
            (aliquota, observacao),
        )


def listar_taxas_diaria_veiculo_admin() -> list[dict]:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM taxas_diaria_veiculo ORDER BY uf")]


def _taxa_diaria_veiculo_duplicada(conn: sqlite3.Connection, uf: str, ignorar_id: int | None = None) -> bool:
    return _existe_duplicata(conn, "taxas_diaria_veiculo", {"uf": uf.strip()}, ignorar_id=ignorar_id)


def inserir_taxa_diaria_veiculo(uf: str, valor_carreta: float, valor_cavalo: float, observacao: str = ""):
    with get_connection() as conn:
        if _taxa_diaria_veiculo_duplicada(conn, uf):
            raise db_conexao.ConflitoIntegridade(f"já existe uma diária de carreta/cavalo cadastrada pra UF '{uf}'")
        cur = conn.execute(
            "INSERT INTO taxas_diaria_veiculo (uf, valor_carreta, valor_cavalo, observacao) VALUES (?,?,?,?)",
            (uf.strip().upper(), valor_carreta, valor_cavalo, observacao),
        )
        return cur.lastrowid


def atualizar_taxa_diaria_veiculo(id_, uf: str, valor_carreta: float, valor_cavalo: float, observacao: str = ""):
    with get_connection() as conn:
        if _taxa_diaria_veiculo_duplicada(conn, uf, ignorar_id=id_):
            raise db_conexao.ConflitoIntegridade(f"já existe uma diária de carreta/cavalo cadastrada pra UF '{uf}'")
        conn.execute(
            "UPDATE taxas_diaria_veiculo SET uf=?, valor_carreta=?, valor_cavalo=?, observacao=? WHERE id=?",
            (uf.strip().upper(), valor_carreta, valor_cavalo, observacao, id_),
        )


def excluir_taxa_diaria_veiculo(id_):
    with get_connection() as conn:
        conn.execute("DELETE FROM taxas_diaria_veiculo WHERE id=?", (id_,))


EIXOS_PEDAGIO = list(range(2, 10))  # números de eixos suportados nas praças de pedágio (2 a 9)


def listar_pracas_pedagio_admin() -> list[dict]:
    with get_connection() as conn:
        return [
            dict(r) for r in conn.execute("SELECT * FROM pracas_pedagio ORDER BY rodovia, nome")
        ]


def _praca_pedagio_duplicada(
    conn: sqlite3.Connection, nome: str, rodovia: str, ignorar_id: int | None = None,
) -> bool:
    """Também usada pelo upsert do import CSV, ver importar_pracas_pedagio_csv."""
    return _existe_duplicata(
        conn, "pracas_pedagio", {"nome": nome.strip(), "rodovia": rodovia.strip()}, ignorar_id=ignorar_id,
    )


def _valores_eixo_tuple(valores_eixo: dict) -> tuple:
    return tuple(valores_eixo.get(n, 0) or 0 for n in EIXOS_PEDAGIO)


def inserir_praca_pedagio(nome, rodovia, concessionaria, uf="", km="",
                           valor_eixo_2=0, valor_eixo_3=0, valor_eixo_4=0, valor_eixo_5=0,
                           valor_eixo_6=0, valor_eixo_7=0, valor_eixo_8=0, valor_eixo_9=0,
                           observacao=""):
    with get_connection() as conn:
        if _praca_pedagio_duplicada(conn, nome, rodovia):
            raise db_conexao.ConflitoIntegridade(f"já existe uma praça de pedágio '{nome}' na rodovia '{rodovia}'")
        cur = conn.execute(
            "INSERT INTO pracas_pedagio (nome, rodovia, concessionaria, uf, km, "
            "valor_eixo_2, valor_eixo_3, valor_eixo_4, valor_eixo_5, valor_eixo_6, "
            "valor_eixo_7, valor_eixo_8, valor_eixo_9, observacao) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (nome, rodovia, concessionaria, uf, km, valor_eixo_2, valor_eixo_3, valor_eixo_4,
             valor_eixo_5, valor_eixo_6, valor_eixo_7, valor_eixo_8, valor_eixo_9, observacao),
        )
        return cur.lastrowid


def atualizar_praca_pedagio(id_, nome, rodovia, concessionaria, uf="", km="",
                             valor_eixo_2=0, valor_eixo_3=0, valor_eixo_4=0, valor_eixo_5=0,
                             valor_eixo_6=0, valor_eixo_7=0, valor_eixo_8=0, valor_eixo_9=0,
                             observacao=""):
    with get_connection() as conn:
        if _praca_pedagio_duplicada(conn, nome, rodovia, ignorar_id=id_):
            raise db_conexao.ConflitoIntegridade(f"já existe uma praça de pedágio '{nome}' na rodovia '{rodovia}'")
        conn.execute(
            "UPDATE pracas_pedagio SET nome=?, rodovia=?, concessionaria=?, uf=?, km=?, "
            "valor_eixo_2=?, valor_eixo_3=?, valor_eixo_4=?, valor_eixo_5=?, valor_eixo_6=?, "
            "valor_eixo_7=?, valor_eixo_8=?, valor_eixo_9=?, observacao=? WHERE id=?",
            (nome, rodovia, concessionaria, uf, km, valor_eixo_2, valor_eixo_3, valor_eixo_4,
             valor_eixo_5, valor_eixo_6, valor_eixo_7, valor_eixo_8, valor_eixo_9, observacao, id_),
        )


def excluir_praca_pedagio(id_):
    with get_connection() as conn:
        conn.execute("DELETE FROM pracas_pedagio WHERE id=?", (id_,))


def listar_pedagios_rota_admin() -> list[dict]:
    with get_connection() as conn:
        return [
            dict(r) for r in conn.execute(
                "SELECT pr.id, pr.cidade_origem, pr.cidade_destino, pr.praca_id, pr.observacao, "
                "pp.nome AS praca_nome, pp.rodovia AS praca_rodovia "
                "FROM pedagios_rota pr JOIN pracas_pedagio pp ON pp.id = pr.praca_id "
                "ORDER BY pr.cidade_origem, pr.cidade_destino, pp.nome"
            )
        ]


def _pedagio_rota_duplicado(
    conn: sqlite3.Connection, cidade_origem: str, cidade_destino: str, praca_id: int,
    ignorar_id: int | None = None,
) -> bool:
    return _existe_duplicata(
        conn, "pedagios_rota",
        {"cidade_origem": cidade_origem.strip(), "cidade_destino": cidade_destino.strip()},
        campos_exatos={"praca_id": praca_id}, ignorar_id=ignorar_id,
    )


def inserir_pedagio_rota(cidade_origem, cidade_destino, praca_id, observacao=""):
    with get_connection() as conn:
        if _pedagio_rota_duplicado(conn, cidade_origem, cidade_destino, praca_id):
            raise db_conexao.ConflitoIntegridade(
                f"já existe um pedágio de rota '{cidade_origem}' → '{cidade_destino}' pra essa praça"
            )
        cur = conn.execute(
            "INSERT INTO pedagios_rota (cidade_origem, cidade_destino, praca_id, observacao) VALUES (?,?,?,?)",
            (cidade_origem, cidade_destino, praca_id, observacao),
        )
        return cur.lastrowid


def atualizar_pedagio_rota(id_, cidade_origem, cidade_destino, praca_id, observacao=""):
    with get_connection() as conn:
        if _pedagio_rota_duplicado(conn, cidade_origem, cidade_destino, praca_id, ignorar_id=id_):
            raise db_conexao.ConflitoIntegridade(
                f"já existe um pedágio de rota '{cidade_origem}' → '{cidade_destino}' pra essa praça"
            )
        conn.execute(
            "UPDATE pedagios_rota SET cidade_origem=?, cidade_destino=?, praca_id=?, observacao=? WHERE id=?",
            (cidade_origem, cidade_destino, praca_id, observacao, id_),
        )


def excluir_pedagio_rota(id_):
    with get_connection() as conn:
        conn.execute("DELETE FROM pedagios_rota WHERE id=?", (id_,))


def listar_distancias_fixas_admin() -> list[dict]:
    with get_connection() as conn:
        return [
            dict(r) for r in conn.execute(
                "SELECT * FROM distancias_fixas ORDER BY cidade_origem, cidade_destino"
            )
        ]


def _distancia_fixa_duplicada(
    conn: sqlite3.Connection, cidade_origem: str, cidade_destino: str, ignorar_id: int | None = None,
) -> bool:
    return _existe_duplicata(
        conn, "distancias_fixas",
        {"cidade_origem": cidade_origem.strip(), "cidade_destino": cidade_destino.strip()},
        ignorar_id=ignorar_id,
    )


def inserir_distancia_fixa(cidade_origem, cidade_destino, distancia_km, observacao=""):
    with get_connection() as conn:
        if _distancia_fixa_duplicada(conn, cidade_origem, cidade_destino):
            raise db_conexao.ConflitoIntegridade(
                f"já existe uma distância fixa cadastrada de '{cidade_origem}' → '{cidade_destino}'"
            )
        cur = conn.execute(
            "INSERT INTO distancias_fixas (cidade_origem, cidade_destino, distancia_km, observacao) "
            "VALUES (?,?,?,?)",
            (cidade_origem, cidade_destino, distancia_km, observacao),
        )
        return cur.lastrowid


def atualizar_distancia_fixa(id_, cidade_origem, cidade_destino, distancia_km, observacao=""):
    with get_connection() as conn:
        if _distancia_fixa_duplicada(conn, cidade_origem, cidade_destino, ignorar_id=id_):
            raise db_conexao.ConflitoIntegridade(
                f"já existe uma distância fixa cadastrada de '{cidade_origem}' → '{cidade_destino}'"
            )
        conn.execute(
            "UPDATE distancias_fixas SET cidade_origem=?, cidade_destino=?, distancia_km=?, observacao=? "
            "WHERE id=?",
            (cidade_origem, cidade_destino, distancia_km, observacao, id_),
        )


def excluir_distancia_fixa(id_):
    with get_connection() as conn:
        conn.execute("DELETE FROM distancias_fixas WHERE id=?", (id_,))


def importar_pracas_pedagio_csv(conteudo: str) -> dict:
    """Importa/atualiza o catálogo de praças de pedágio a partir de um CSV
    no mesmo formato publicado pelas concessionárias (uma linha por praça,
    uma coluna por número de eixos). Colunas esperadas no cabeçalho
    (case-insensitive): nome, rodovia, concessionaria, uf, km,
    valor_eixo_2..valor_eixo_9, observacao -- todas exceto nome/rodovia/
    concessionaria são opcionais. Faz upsert por (nome, rodovia): atualiza
    se já existir uma praça com esse nome nessa rodovia, senão insere."""
    criadas = 0
    atualizadas = 0
    erros: list[str] = []
    leitor = csv.DictReader(io.StringIO(conteudo))
    with get_connection() as conn:
        for i, linha in enumerate(leitor, start=2):  # linha 1 é o cabeçalho
            campos = {(k or "").strip().lower(): (v or "").strip() for k, v in linha.items()}
            nome = campos.get("nome", "")
            rodovia = campos.get("rodovia", "")
            concessionaria = campos.get("concessionaria", "")
            if not nome or not rodovia or not concessionaria:
                erros.append(f"linha {i}: nome, rodovia e concessionaria são obrigatórios")
                continue
            try:
                valores_eixo = {
                    n: (float(campos[f"valor_eixo_{n}"].replace(",", ".")) if campos.get(f"valor_eixo_{n}") else 0)
                    for n in EIXOS_PEDAGIO
                }
            except ValueError:
                erros.append(f"linha {i}: valor de eixo inválido")
                continue
            uf, km, observacao = campos.get("uf", ""), campos.get("km", ""), campos.get("observacao", "")
            existente = conn.execute(
                "SELECT id FROM pracas_pedagio WHERE LOWER(nome) = LOWER(?) AND LOWER(rodovia) = LOWER(?)",
                (nome, rodovia),
            ).fetchone()
            if existente:
                conn.execute(
                    "UPDATE pracas_pedagio SET concessionaria=?, uf=?, km=?, "
                    "valor_eixo_2=?, valor_eixo_3=?, valor_eixo_4=?, valor_eixo_5=?, valor_eixo_6=?, "
                    "valor_eixo_7=?, valor_eixo_8=?, valor_eixo_9=?, observacao=? WHERE id=?",
                    (concessionaria, uf, km, *_valores_eixo_tuple(valores_eixo), observacao, existente["id"]),
                )
                atualizadas += 1
            else:
                conn.execute(
                    "INSERT INTO pracas_pedagio (nome, rodovia, concessionaria, uf, km, "
                    "valor_eixo_2, valor_eixo_3, valor_eixo_4, valor_eixo_5, valor_eixo_6, "
                    "valor_eixo_7, valor_eixo_8, valor_eixo_9, observacao) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (nome, rodovia, concessionaria, uf, km, *_valores_eixo_tuple(valores_eixo), observacao),
                )
                criadas += 1
    return {"criadas": criadas, "atualizadas": atualizadas, "erros": erros}


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
    """Versão sem `dados_json` (snapshot completo, pode ter vários KB por
    linha) -- quem lista o histórico (GET /historico) nunca usa esse
    campo, só GET /historico/{codigo} (ver _buscar_historico_com_dados em
    routers/historico.py), então não há motivo pra trazer do banco."""
    with get_connection() as conn:
        return [
            dict(r) for r in conn.execute(
                """SELECT id, codigo, criado_em, cliente, responsavel, origem_resumo,
                          destino_resumo, veiculo, distancia_km, valor_mercadoria,
                          frete_total, status, criado_por
                   FROM orcamentos_historico ORDER BY id DESC"""
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


def atualizar_pedagio_historico(
    id_: int, frete_total: float, dados_json: str,
    pedagio_antigo: float, pedagio_novo: float, alterado_por: str = "",
    dados_json_esperado: str | None = None,
):
    """Usado só pra corrigir o pedágio de um orçamento já salvo (ex: o
    valor estimado pelo Google Maps na hora da cotação estava errado) —
    ver routers/historico.py, que recalcula frete_total e o dados_json
    antes de chamar essa função. Não mexe em mais nenhum campo do
    orçamento salvo, além de registrar a alteração em
    orcamentos_historico_alteracoes (ver listar_alteracoes_historico) pra
    manter rastro de quem mudou o quê.

    `dados_json_esperado` é o snapshot que o chamador leu antes de
    calcular o novo valor (controle de concorrência otimista) -- se o
    registro mudou nesse meio tempo (outra edição concorrente no mesmo
    id), o snapshot atual não bate mais com o esperado e a escrita é
    rejeitada em vez de sobrescrever silenciosamente a mudança da outra
    edição."""
    with get_connection() as conn:
        if dados_json_esperado is not None:
            atual = conn.execute(
                "SELECT dados_json FROM orcamentos_historico WHERE id=?", (id_,)
            ).fetchone()
            if not atual or atual["dados_json"] != dados_json_esperado:
                raise db_conexao.ConflitoIntegridade(
                    "Este orçamento foi alterado por outra operação enquanto você editava -- recarregue e tente de novo."
                )
        conn.execute(
            "UPDATE orcamentos_historico SET frete_total=?, dados_json=? WHERE id=?",
            (frete_total, dados_json, id_),
        )
        conn.execute(
            """INSERT INTO orcamentos_historico_alteracoes
               (historico_id, campo, valor_antigo, valor_novo, alterado_por, alterado_em)
               VALUES (?,?,?,?,?,?)""",
            (id_, "pedagio", pedagio_antigo, pedagio_novo, alterado_por,
             datetime.now().isoformat(timespec="seconds")),
        )


def atualizar_recalculo_historico(
    id_: int, frete_total: float, dados_json: str,
    frete_total_antigo: float, alterado_por: str = "",
    dados_json_esperado: str | None = None,
):
    """Usado pra recalcular um orçamento já salvo com os parâmetros ATUAIS
    da Tabela de Preços (ex: depois de um reajuste que deve valer
    retroativamente pros orçamentos já cotados) -- sobrescreve
    frete_total e o dados_json inteiro (diferente de
    atualizar_pedagio_historico, que só ajusta o campo pedágio dentro do
    snapshot) e registra em orcamentos_historico_alteracoes pra manter
    rastro de quem/quando recalculou.

    `dados_json_esperado`: mesmo controle de concorrência otimista de
    atualizar_pedagio_historico (ver lá)."""
    with get_connection() as conn:
        if dados_json_esperado is not None:
            atual = conn.execute(
                "SELECT dados_json FROM orcamentos_historico WHERE id=?", (id_,)
            ).fetchone()
            if not atual or atual["dados_json"] != dados_json_esperado:
                raise db_conexao.ConflitoIntegridade(
                    "Este orçamento foi alterado por outra operação enquanto você editava -- recarregue e tente de novo."
                )
        conn.execute(
            "UPDATE orcamentos_historico SET frete_total=?, dados_json=? WHERE id=?",
            (frete_total, dados_json, id_),
        )
        conn.execute(
            """INSERT INTO orcamentos_historico_alteracoes
               (historico_id, campo, valor_antigo, valor_novo, alterado_por, alterado_em)
               VALUES (?,?,?,?,?,?)""",
            (id_, "recalculo_precos", frete_total_antigo, frete_total, alterado_por,
             datetime.now().isoformat(timespec="seconds")),
        )


def listar_alteracoes_historico(historico_id: int) -> list[dict]:
    """Histórico de edições feitas num orçamento salvo (ver
    atualizar_pedagio_historico) — usado pra mostrar no detalhe do
    orçamento (GET /historico/{codigo}) o que foi alterado depois de
    salvo, com valor antigo/novo, quem e quando."""
    with get_connection() as conn:
        return [
            dict(r) for r in conn.execute(
                """SELECT campo, valor_antigo, valor_novo, alterado_por, alterado_em
                   FROM orcamentos_historico_alteracoes
                   WHERE historico_id = ? ORDER BY id""",
                (historico_id,),
            )
        ]


# ============================================================
# Usuários e sessões (login) — as senhas nunca são retornadas
# pelas funções "_admin"; ver auth_service.py para hash/verificação.
# ============================================================

def _usuario_duplicado(conn: sqlite3.Connection, username: str, ignorar_id: int | None = None) -> bool:
    return _existe_duplicata(conn, "usuarios", {"username": username.strip()}, ignorar_id=ignorar_id)


def listar_usuarios_admin() -> list[dict]:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id, nome, username, role, ativo, criado_em, deve_trocar_senha FROM usuarios ORDER BY nome"
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


def inserir_usuario(
    nome: str, username: str, senha_hash: str, senha_salt: str, role: str, ativo: bool = True,
    deve_trocar_senha: bool = False,
) -> int:
    with get_connection() as conn:
        if _usuario_duplicado(conn, username):
            raise db_conexao.ConflitoIntegridade(f"já existe um usuário com o login '{username}'")
        cur = conn.execute(
            "INSERT INTO usuarios (nome, username, senha_hash, senha_salt, role, ativo, criado_em, deve_trocar_senha) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                nome, username, senha_hash, senha_salt, role, int(ativo),
                datetime.now().isoformat(timespec="seconds"), int(deve_trocar_senha),
            ),
        )
        return cur.lastrowid


def atualizar_usuario(id_: int, nome: str, username: str, role: str, ativo: bool):
    with get_connection() as conn:
        if _usuario_duplicado(conn, username, ignorar_id=id_):
            raise db_conexao.ConflitoIntegridade(f"já existe um usuário com o login '{username}'")
        conn.execute(
            "UPDATE usuarios SET nome=?, username=?, role=?, ativo=? WHERE id=?",
            (nome, username, role, int(ativo), id_),
        )


def atualizar_senha_usuario(id_: int, senha_hash: str, senha_salt: str):
    with get_connection() as conn:
        # Trocar a senha também limpa o sinalizador de troca obrigatória
        # (ex: senha padrão do admin) — a exigência já foi cumprida.
        conn.execute(
            "UPDATE usuarios SET senha_hash=?, senha_salt=?, deve_trocar_senha=0 WHERE id=?",
            (senha_hash, senha_salt, id_),
        )


def marcar_deve_trocar_senha(id_: int):
    with get_connection() as conn:
        conn.execute("UPDATE usuarios SET deve_trocar_senha=1 WHERE id=?", (id_,))


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
            "SELECT s.expira_em, u.id, u.nome, u.username, u.role, u.ativo, u.deve_trocar_senha "
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