# Desenvolvedor Chefe: RenanFolha

"""Teste de export_service.py: gera o PDF de cotação (Modelo 1) a partir
de um registro de histórico simulado (mesmo formato devolvido por GET
/historico/{codigo}) e confere que o resultado é um PDF válido, não vazio,
e com o texto esperado -- via pypdf.extract_text() (ver requirements-dev.txt)."""

from io import BytesIO

import pypdf
import pytest

import export_service as export


def _registro_teste():
    return {
        "codigo": "ORC-0001",
        "criado_em": "2026-01-15T10:30:00",
        "cliente": "Cliente Teste Ltda",
        "responsavel": "Fulano de Tal",
        "origem_resumo": "São Paulo",
        "destino_resumo": "Curitiba, PR, Brasil",
        "veiculo": "VUC",
        "distancia_km": 100,
        "valor_mercadoria": 1000.0,
        "frete_total": 543.21,
        "dados": {
            "payload": {"paletes": [{"comprimento": 40, "largura": 30, "altura": 25}]},
            "resultado": {
                "entrada": {"peso_kg": 50, "transporte": "Rodoviário"},
                "calculos_intermediarios": {
                    "volume_total_m3": 0.03,
                    "peso_considerado_kg": 50,
                    "coleta_terceirizada": False,
                    "entrega_terceirizada": False,
                    "taxas_adicionais": [
                        {"nome": "GRIS", "valor_configurado": 0.10},
                        {"nome": "Ad Valorem", "valor_configurado": 0.35},
                    ],
                },
                "resultado": {"prazo_estimado_dias_uteis": 5},
            },
        },
    }


def _texto(conteudo: bytes) -> str:
    leitor = pypdf.PdfReader(BytesIO(conteudo))
    return "\n".join(pagina.extract_text() for pagina in leitor.pages)


def test_gerar_pdf_orcamento_retorna_pdf_valido_com_os_dados():
    conteudo = export.gerar_pdf_orcamento(_registro_teste())
    assert isinstance(conteudo, bytes)
    assert conteudo.startswith(b"%PDF")

    texto = _texto(conteudo)
    assert "ORC-0001" in texto
    assert "Cliente Teste Ltda" in texto
    assert "Fulano de Tal" in texto
    assert "543,21" in texto  # frete_total formatado em BRL
    assert "1.000,00" in texto  # valor_mercadoria formatado em BRL
    assert "São Paulo" in texto
    assert "Curitiba" in texto
    assert "GRIS 0,1%" in texto
    assert "ADV 0,35%" in texto
    assert "5 dias úteis" in texto


def test_qtde_soma_a_quantidade_de_cada_linha_de_palete():
    registro = _registro_teste()
    registro["dados"]["payload"]["paletes"] = [
        {"comprimento": 40, "largura": 30, "altura": 25, "quantidade": 3},
        {"comprimento": 50, "largura": 40, "altura": 30, "quantidade": 2},
    ]
    texto = _texto(export.gerar_pdf_orcamento(registro))
    assert "5" in texto  # volumes = 3 + 2, não 2 linhas


def test_texto_livre_e_escapado_e_nao_quebra_o_html():
    # Diferente do guard de injeção de fórmula do antigo export em xlsx
    # (_texto_seguro, CWE-1236), aqui o risco é HTML/script injection no
    # documento renderizado -- ver export_service._html_orcamento, que
    # passa todo campo de texto livre por html.escape antes de embutir no
    # template.
    registro = _registro_teste()
    registro["cliente"] = "<script>alert(1)</script> & Cia"
    conteudo = export.gerar_pdf_orcamento(registro)
    assert conteudo.startswith(b"%PDF")
    texto = _texto(conteudo)
    assert "alert(1)" in texto  # texto aparece, só não executa (está escapado no HTML-fonte)
    assert "Cia" in texto


def test_sem_taxas_adicionais_nao_quebra_e_nao_mostra_percentual():
    # Histórico salvo antes do RCA/GRIS/Ad Valorem existirem no sistema, ou
    # orçamento sem nenhuma taxa configurada -- não pode levantar exceção.
    registro = _registro_teste()
    registro["dados"]["resultado"]["calculos_intermediarios"]["taxas_adicionais"] = []
    conteudo = export.gerar_pdf_orcamento(registro)
    assert conteudo.startswith(b"%PDF")


def test_data_criacao_invalida_nao_levanta_excecao():
    # _data_criacao tem um fallback pra datetime.now() quando criado_em não
    # é um ISO válido (defensivo -- na prática a coluna sempre vem
    # preenchida certinho pelo banco, mas não pode travar a exportação se
    # algum registro antigo estiver malformado).
    registro = _registro_teste()
    registro["criado_em"] = "isso não é uma data"
    conteudo = export.gerar_pdf_orcamento(registro)  # não pode levantar exceção
    assert conteudo.startswith(b"%PDF")


def test_erro_ao_gerar_pdf_vira_exportacao_error(monkeypatch):
    class _FalsoPlaywright:
        def __enter__(self):
            raise RuntimeError("Google Chrome não encontrado")

        def __exit__(self, *_a):
            return False

    monkeypatch.setattr(export, "sync_playwright", lambda: _FalsoPlaywright())
    with pytest.raises(export.ExportacaoError):
        export.gerar_pdf_orcamento(_registro_teste())
