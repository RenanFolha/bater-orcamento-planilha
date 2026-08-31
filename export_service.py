# Desenvolvedor Chefe: RenanFolha

"""
Exportação de um orçamento do histórico para o formato da planilha
"Modelo de Orçamento.xlsx" (usada pelo time comercial pra mandar cotação
pro cliente).

Carrega o arquivo modelo (mantém título, cabeçalho e o bloco de
generalidades/taxas já formatado) e só preenche a linha de dados
(linha 6, logo abaixo do cabeçalho) com os valores do orçamento.
"""

from datetime import datetime
from io import BytesIO
from pathlib import Path

import openpyxl

import frete_service as fs

MODELO_PATH = Path(__file__).resolve().parent / "Modelo de Orçamento.xlsx"

_LINHA_CABECALHO = 5
_LINHA_DADOS = _LINHA_CABECALHO + 1


class ExportacaoError(Exception):
    """Erro ao gerar a planilha de exportação."""


def _data_criacao(criado_em: str) -> datetime:
    try:
        return datetime.fromisoformat(criado_em)
    except (TypeError, ValueError):
        return datetime.now()


def gerar_planilha_orcamento(registro: dict) -> bytes:
    """Recebe um registro de histórico (como devolvido por
    GET /historico/{codigo}, já com `dados` decodificado) e devolve os
    bytes do .xlsx preenchido a partir do modelo."""
    if not MODELO_PATH.exists():
        raise ExportacaoError(f"Planilha modelo não encontrada em '{MODELO_PATH.name}'.")

    dados = registro.get("dados") or {}
    payload = dados.get("payload") or {}
    resultado = dados.get("resultado") or {}
    entrada = resultado.get("entrada") or {}
    calc = resultado.get("calculos_intermediarios") or {}
    resultado_final = resultado.get("resultado") or {}

    cidade_origem, uf_origem = fs.cidade_e_uf(registro.get("origem_resumo") or "")
    cidade_destino, uf_destino = fs.cidade_e_uf(registro.get("destino_resumo") or "")

    def _local(cidade: str | None, uf: str, resumo_fallback: str) -> str:
        base = cidade or resumo_fallback or ""
        return f"{base}/{uf}" if base and uf else base

    codigo = registro.get("codigo") or ""
    cliente_nome = (registro.get("cliente") or "").strip()
    origem_assunto = _local(cidade_origem, uf_origem, registro.get("origem_resumo") or "")
    destino_assunto = _local(cidade_destino, uf_destino, registro.get("destino_resumo") or "")
    assunto = " - ".join(
        parte for parte in (
            f"ID {codigo}" if codigo else None,
            f"CLIENTE {cliente_nome.upper()}" if cliente_nome else None,
            origem_assunto or None,
            destino_assunto or None,
        ) if parte
    )

    observacoes = []
    if calc.get("coleta_terceirizada"):
        nome = calc.get("transportadora_coleta_nome") or ""
        observacoes.append(f"Coleta terceirizada ({nome})" if nome else "Coleta terceirizada")
    if calc.get("entrega_terceirizada"):
        nome = calc.get("transportadora_entrega_nome") or ""
        observacoes.append(f"Entrega terceirizada ({nome})" if nome else "Entrega terceirizada")

    wb = openpyxl.load_workbook(MODELO_PATH)
    ws = wb[wb.sheetnames[0]]

    ws["D3"] = f"ORÇAMENTO DE FRETE - CLIENTE {(registro.get('cliente') or '').upper()}".strip(" -")
    ws["N3"] = _data_criacao(registro.get("criado_em"))

    ws.cell(row=_LINHA_DADOS, column=2, value=codigo)  # B: ID COTAÇÃO
    ws.cell(row=_LINHA_DADOS, column=3, value=cidade_origem or registro.get("origem_resumo") or "")  # C
    ws.cell(row=_LINHA_DADOS, column=4, value=uf_origem)  # D
    ws.cell(row=_LINHA_DADOS, column=5, value=cidade_destino or registro.get("destino_resumo") or "")  # E
    ws.cell(row=_LINHA_DADOS, column=6, value=uf_destino)  # F
    ws.cell(row=_LINHA_DADOS, column=7, value=registro.get("valor_mercadoria") or 0)  # G
    # soma a quantidade de cada linha de palete (uma linha pode
    # representar vários paletes idênticos, não só um), não a contagem
    # de linhas do formulário
    qtde_paletes = sum((p.get("quantidade") or 1) for p in (payload.get("paletes") or []))
    ws.cell(row=_LINHA_DADOS, column=8, value=qtde_paletes)  # H: QTDE
    ws.cell(row=_LINHA_DADOS, column=9, value=entrada.get("peso_kg") or 0)  # I: PESO
    ws.cell(row=_LINHA_DADOS, column=10, value=calc.get("volume_total_m3") or 0)  # J: M³
    ws.cell(row=_LINHA_DADOS, column=11, value=calc.get("peso_considerado_kg") or 0)  # K: PESO CALCULO
    ws.cell(row=_LINHA_DADOS, column=12, value=registro.get("frete_total") or 0)  # L: FRETE FINAL
    prazo = resultado_final.get("prazo_estimado_dias_uteis")
    ws.cell(row=_LINHA_DADOS, column=13, value=f"{prazo} dias úteis" if prazo is not None else "")  # M
    ws.cell(row=_LINHA_DADOS, column=14, value=entrada.get("transporte") or registro.get("veiculo") or "")  # N
    ws.cell(row=_LINHA_DADOS, column=15, value="; ".join(observacoes))  # O
    ws.cell(row=_LINHA_DADOS, column=18, value=assunto)  # R: ASSUNTO

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
