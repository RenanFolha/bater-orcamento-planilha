# Desenvolvedor Chefe: RenanFolha

"""
Testes de transportadoras_terceirizadas (frete_db.py): tabela começa
vazia (não tem seed — ver comentário em _seed_se_vazio), `tipo` tem
CHECK ('coleta', 'entrega' ou 'ambos') e `UNIQUE(nome, cidade)` — a
mesma transportadora não pode ser cadastrada duas vezes pra mesma
cidade (nome OU cidade diferentes não conflitam, só a combinação
exata). Usa o fixture `banco_temporario` (conftest.py) — nunca toca
no frete.db real.
"""

import pytest

import db_conexao
import frete_db as db


def test_inserir_e_listar_transportadora_terceirizada(banco_temporario):
    id_ = db.inserir_transportadora_terceirizada(
        "Rápido Norte", "Manaus", "ambos", 450.00, "acordo mensal"
    )
    assert id_ is not None
    linhas = db.listar_transportadoras_terceirizadas_admin()
    assert len(linhas) == 1
    assert linhas[0]["nome"] == "Rápido Norte"
    assert linhas[0]["cidade"] == "Manaus"
    assert linhas[0]["tipo"] == "ambos"
    assert linhas[0]["valor"] == 450.00
    assert linhas[0]["observacao"] == "acordo mensal"


def test_mesma_transportadora_mesma_cidade_da_conflito(banco_temporario):
    db.inserir_transportadora_terceirizada("Rápido Norte", "Manaus", "ambos", 450.00)
    with pytest.raises(db_conexao.ConflitoIntegridade):
        db.inserir_transportadora_terceirizada("Rápido Norte", "Manaus", "ambos", 480.00)


def test_mesmo_nome_cidade_diferente_nao_conflita(banco_temporario):
    db.inserir_transportadora_terceirizada("Rápido Norte", "Manaus", "ambos", 450.00)
    id2 = db.inserir_transportadora_terceirizada("Rápido Norte", "Belém", "ambos", 400.00)
    assert id2 is not None
    assert len(db.listar_transportadoras_terceirizadas_admin()) == 2


def test_nome_diferente_mesma_cidade_nao_conflita(banco_temporario):
    db.inserir_transportadora_terceirizada("Rápido Norte", "Manaus", "ambos", 450.00)
    id2 = db.inserir_transportadora_terceirizada("Outra Transportadora", "Manaus", "ambos", 470.00)
    assert id2 is not None
    assert len(db.listar_transportadoras_terceirizadas_admin()) == 2


def test_tipo_invalido_da_erro(banco_temporario):
    with pytest.raises(db_conexao.ConflitoIntegridade):
        db.inserir_transportadora_terceirizada("Rápido Norte", "Manaus", "retirada", 450.00)


def test_atualizar_transportadora_terceirizada(banco_temporario):
    id_ = db.inserir_transportadora_terceirizada("Rápido Norte", "Manaus", "ambos", 450.00)
    db.atualizar_transportadora_terceirizada(id_, "Rápido Norte", "Manaus", "coleta", 480.00, "reajuste")
    linha = db.listar_transportadoras_terceirizadas_admin()[0]
    assert linha["tipo"] == "coleta"
    assert linha["valor"] == 480.00
    assert linha["observacao"] == "reajuste"


def test_atualizar_transportadora_terceirizada_nao_pode_roubar_combinacao_de_outra_linha(banco_temporario):
    db.inserir_transportadora_terceirizada("Rápido Norte", "Manaus", "ambos", 450.00)
    id2 = db.inserir_transportadora_terceirizada("Rápido Norte", "Belém", "ambos", 400.00)
    with pytest.raises(db_conexao.ConflitoIntegridade):
        db.atualizar_transportadora_terceirizada(id2, "Rápido Norte", "Manaus", "ambos", 400.00)


def test_excluir_transportadora_terceirizada(banco_temporario):
    id_ = db.inserir_transportadora_terceirizada("Rápido Norte", "Manaus", "ambos", 450.00)
    db.excluir_transportadora_terceirizada(id_)
    assert db.listar_transportadoras_terceirizadas_admin() == []


def test_migracao_do_schema_antigo_preserva_linhas_sem_duplicata(banco_temporario):
    # simula um banco no schema anterior (sem UNIQUE nenhuma) com uma
    # linha duplicada e confirma que _migrar_transportadoras_terceirizadas_unique
    # recria a tabela preservando as linhas únicas (mantém a de menor id
    # em caso de duplicata) sem quebrar nem perder as demais.
    with db.get_connection() as conn:
        conn.execute("DROP TABLE transportadoras_terceirizadas")
        conn.execute("""
            CREATE TABLE transportadoras_terceirizadas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                cidade TEXT NOT NULL,
                tipo TEXT NOT NULL DEFAULT 'ambos' CHECK (tipo IN ('coleta', 'entrega', 'ambos')),
                valor REAL NOT NULL,
                observacao TEXT DEFAULT ''
            )
        """)
        conn.executemany(
            "INSERT INTO transportadoras_terceirizadas (id, nome, cidade, tipo, valor, observacao) VALUES (?,?,?,?,?,?)",
            [
                (1, "Rápido Norte", "Manaus", "ambos", 450.00, ""),
                (2, "Rápido Norte", "Manaus", "ambos", 480.00, "duplicata antiga"),
                (3, "Outra Transportadora", "Belém", "coleta", 300.00, ""),
            ],
        )
        conn.commit()

    with db.get_connection() as conn:
        db._migrar_transportadoras_terceirizadas_unique(conn)
        conn.commit()

    linhas = db.listar_transportadoras_terceirizadas_admin()
    assert {r["id"] for r in linhas} == {1, 3}

    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='transportadoras_terceirizadas'"
        ).fetchone()
    assert "UNIQUE(nome, cidade)" in (row["sql"] or "")
