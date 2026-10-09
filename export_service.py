# Desenvolvedor Chefe: RenanFolha

"""
Exportação de um orçamento do histórico pra PDF -- documento de página
única, estilo proposta comercial, pronto pra mandar direto pro cliente
("Modelo 1 -- Cotação única", escolhido pelo usuário entre 3 mockups
comparados nessa sessão; os outros dois, cotação múltipla com custos
segregados e comparativo de modais, exigiriam funcionalidades que o
sistema não tem hoje -- ver CONTEXTO.md).

Antes disso a exportação preenchia uma linha da planilha "Modelo de
Orçamento.xlsx" (um log tabular, uma linha por cotação) -- esse formato
foi inteiramente substituído, por pedido explícito do usuário.

Gerado a partir de HTML/CSS renderizado pelo Google Chrome já instalado
no sistema (ver playwright, channel="chrome") -- não baixa nenhum
Chromium próprio, só dirige o Chrome existente pra imprimir em PDF, então
não precisa rodar `playwright install` (só `pip install playwright`,
ver requirements.txt) nem lida com o download de ~150MB de binário que
isso implicaria.
"""

from datetime import datetime, timedelta
from html import escape as _esc
from pathlib import Path

from playwright.sync_api import sync_playwright

import frete_service as fs

_LOGO_PATH = Path(__file__).resolve().parent / "assets" / "supersonic-logo-light.png"
_VALIDADE_DIAS = 15

# Dados fixos da empresa pro rodapé/cabeçalho -- não existe cadastro de
# CNPJ/endereço/contato comercial em nenhuma tabela do banco hoje, então
# ficam aqui como constante (ajustar se mudar). E-mail/telefone/razão
# social vieram do mockup aprovado e foram confirmados com o usuário.
# Endereço é o mesmo já cadastrado pra filial São Paulo em frete_db.py
# (_seed_filiais) -- fonte real, não o mockup.
_EMPRESA_RAZAO_SOCIAL = "SuperSonic Logística e Transportes Ltda"
_EMPRESA_CNPJ = "47.705.660/0001-31"
_EMPRESA_ENDERECO = (
    "Av. Otaviano Alves de Lima, nº 2724, Bloco B, 4º andar, "
    "Jardim das Graças, São Paulo/SP — CEP 02.701-000"
)
_EMPRESA_SITE = "supersonic.com.br"
_CONTATO_EMAIL = "cotacao@ssonic.com.br"
_CONTATO_TELEFONE = "(11) 97401-0527"


class ExportacaoError(Exception):
    """Erro ao gerar o PDF de exportação."""


def _data_criacao(criado_em: str) -> datetime:
    try:
        return datetime.fromisoformat(criado_em)
    except (TypeError, ValueError):
        return datetime.now()


def _fmt_data(d: datetime) -> str:
    return d.strftime("%d/%m/%Y")


def _fmt_brl(valor) -> str:
    try:
        n = float(valor or 0)
    except (TypeError, ValueError):
        n = 0.0
    texto = f"{n:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {texto}"


def _fmt_num(valor, casas=0) -> str:
    try:
        n = float(valor or 0)
    except (TypeError, ValueError):
        n = 0.0
    texto = f"{n:,.{casas}f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return texto


def _taxa_pct(calc: dict, nome: str) -> float | None:
    """Busca o % configurado de uma taxa adicional (GRIS/Ad Valorem/RCA)
    no detalhamento salvo no snapshot -- ver frete_service.
    _taxas_adicionais_aplicadas. None quando a cotação é anterior a essa
    taxa existir no sistema (ex: histórico salvo antes do RCA, ver
    CONTEXTO.md) ou quando não está cadastrada."""
    chave = nome.strip().lower()
    for taxa in calc.get("taxas_adicionais") or []:
        if (taxa.get("nome") or "").strip().lower() == chave:
            return taxa.get("valor_configurado")
    return None


def _fmt_pct(valor: float | None) -> str:
    if valor is None:
        return "—"
    texto = f"{valor:.2f}".rstrip("0").rstrip(".")
    return f"{texto.replace('.', ',')}%"


def _tipo_orcamento(payload: dict) -> str:
    """Lotação (veículo escolhido automaticamente pelo peso) não tem
    campo 'veiculo' no payload salvo; Fracionado sempre tem (é
    obrigatório em OrcamentoFracionadoRequest, só como referência pra
    pedágio/balsa/coleta fixa) -- mesmo critério usado em
    routers/historico.py::recalcular_historico pra distinguir os dois."""
    return "Fracionado (LTL)" if "veiculo" in payload else "Lotação (FTL)"


def _html_orcamento(registro: dict) -> str:
    dados = registro.get("dados") or {}
    payload = dados.get("payload") or {}
    resultado = dados.get("resultado") or {}
    entrada = resultado.get("entrada") or {}
    calc = resultado.get("calculos_intermediarios") or {}
    resultado_final = resultado.get("resultado") or {}

    cidade_origem, uf_origem = fs.cidade_e_uf(registro.get("origem_resumo") or "")
    cidade_destino, uf_destino = fs.cidade_e_uf(registro.get("destino_resumo") or "")
    cidade_origem = cidade_origem or (registro.get("origem_resumo") or "").split(",")[0]
    cidade_destino = cidade_destino or (registro.get("destino_resumo") or "").split(",")[0]

    codigo = registro.get("codigo") or ""
    criado_em = _data_criacao(registro.get("criado_em"))
    validade = criado_em + timedelta(days=_VALIDADE_DIAS)

    qtde_paletes = sum((p.get("quantidade") or 1) for p in (payload.get("paletes") or []))
    fator_cubagem = calc.get("fator_cubagem")
    observacao_carga = (
        f"Fator {fator_cubagem:.0f} kg/m³. Peso e cubagem informados pelo cliente."
        if fator_cubagem else "Peso e cubagem informados pelo cliente."
    )

    gris_pct = _taxa_pct(calc, "GRIS")
    adv_pct = _taxa_pct(calc, "Ad Valorem")
    rca_pct = _taxa_pct(calc, "RCA")
    taxas_resumo = " · ".join(
        f"{nome} {_fmt_pct(valor)}" for nome, valor in (("RCA", rca_pct), ("GRIS", gris_pct), ("ADV", adv_pct))
        if valor is not None
    )
    taxas_seguro = ", ".join(
        f"{nome} {_fmt_pct(valor)}" for nome, valor in (("RCA", rca_pct), ("GRIS", gris_pct), ("ADV", adv_pct))
        if valor is not None
    )

    prazo = resultado_final.get("prazo_estimado_dias_uteis")
    prazo_texto = f"{prazo} dias úteis" if prazo is not None else "a combinar"

    logo_tag = ""
    if _LOGO_PATH.exists():
        import base64
        logo_b64 = base64.b64encode(_LOGO_PATH.read_bytes()).decode("ascii")
        logo_tag = f'<img src="data:image/png;base64,{logo_b64}" class="logo-mark" alt="">'

    e = _esc  # atalho -- todo texto livre (cliente/responsável/cidade) precisa passar por aqui
    responsavel = (registro.get("responsavel") or "").strip() or "Equipe comercial"

    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><style>
@page {{ size: A4; margin: 18mm 16mm; }}
* {{ box-sizing: border-box; }}
body {{
  font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  color: #16202C; font-size: 11px; margin: 0;
}}
.eyebrow {{ font-size: 9.5px; letter-spacing: 1px; text-transform: uppercase; color: #0B85AD; font-weight: 600; }}
.dim {{ color: #717C89; }}
.header {{ display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 1px solid #E2E8EE; padding-bottom: 14px; }}
.brand {{ display: flex; align-items: center; gap: 8px; }}
.brand .logo-mark {{ width: 26px; height: 26px; }}
.brand .word {{ font-size: 18px; font-weight: 800; letter-spacing: 0.5px; }}
.header .codigo {{ font-size: 24px; font-weight: 800; margin: 2px 0; }}
.header .right {{ text-align: right; }}

.linha-contatos {{ display: flex; justify-content: space-between; padding: 16px 0; }}
.linha-contatos .nome {{ font-size: 13px; font-weight: 700; margin-top: 2px; }}
.linha-contatos .right {{ text-align: right; }}

.route-box {{ border: 1px solid #E2E8EE; border-radius: 10px; overflow: hidden; }}
.route-top {{ display: flex; }}
.route-left {{ flex: 1.4; background: #F3F5F7; padding: 14px 18px; }}
.route-left .cidades {{ display: flex; align-items: center; gap: 10px; margin-top: 2px; }}
.route-left .cidade {{ font-size: 17px; font-weight: 800; }}
.route-left .cidade .uf {{ display: block; font-size: 9px; font-weight: 400; color: #717C89; text-transform: uppercase; }}
.route-left .arrow {{ color: #0EA5D1; font-size: 15px; }}
.route-right {{ flex: 1; background: #1C2B3A; color: #fff; padding: 14px 18px; }}
.route-right .total {{ font-size: 24px; font-weight: 800; margin-top: 2px; }}
.route-right .inclui {{ font-size: 9px; color: #AEC2D1; margin-top: 8px; line-height: 1.5; }}
.route-bottom {{ display: flex; background: #F3F5F7; border-top: 1px solid #E2E8EE; }}
.route-bottom > div {{ flex: 1; padding: 10px 18px; }}
.route-bottom > div + div {{ border-left: 1px solid #E2E8EE; }}
.route-bottom .v {{ font-weight: 700; margin-top: 2px; }}

.secao {{ margin-top: 18px; }}
.secao-titulo {{ font-size: 9.5px; letter-spacing: 1px; text-transform: uppercase; font-weight: 700; border-bottom: 1px solid #E2E8EE; padding-bottom: 6px; margin-bottom: 10px; }}

table.carga {{ width: 100%; border-collapse: collapse; }}
table.carga th {{ text-align: left; font-size: 9px; text-transform: uppercase; letter-spacing: 0.5px; color: #717C89; font-weight: 600; padding-bottom: 6px; }}
table.carga td {{ padding-top: 2px; font-weight: 600; }}
table.carga td.obs {{ font-weight: 400; color: #717C89; }}

.cards {{ display: flex; gap: 10px; }}
.cards .card {{ flex: 1; border: 1px solid #E2E8EE; border-radius: 8px; padding: 10px 12px; }}
.cards .card .t {{ font-weight: 700; font-size: 11.5px; }}
.cards .card .v {{ margin-top: 4px; }}
.cards .card .s {{ font-size: 8.5px; color: #717C89; text-transform: uppercase; margin-top: 2px; }}

.notas {{ display: flex; gap: 32px; margin-top: 14px; }}
.notas > div {{ flex: 1; }}
.notas .label {{ font-weight: 700; display: inline; }}

.footer {{ border-top: 1px solid #E2E8EE; margin-top: 20px; padding-top: 14px; display: flex; justify-content: space-between; align-items: center; gap: 20px; }}
.footer .texto {{ font-size: 10px; color: #717C89; }}
.btn {{ background: #1CA7DE; color: #fff; font-weight: 700; font-size: 11px; padding: 9px 18px; border-radius: 6px; text-decoration: none; white-space: nowrap; }}
.rodape-empresa {{ display: flex; justify-content: space-between; margin-top: 10px; font-size: 9px; color: #9AA5B1; }}
</style></head>
<body>

  <div class="header">
    <div class="brand">
      {logo_tag}
      <span class="word">SUPERSONIC</span>
    </div>
    <div class="right">
      <div class="eyebrow">Cotação de frete</div>
      <div class="codigo">{e(codigo)}</div>
      <div class="dim">Emitida em <b>{_fmt_data(criado_em)}</b> · Válida até <b>{_fmt_data(validade)}</b></div>
    </div>
  </div>

  <div class="linha-contatos">
    <div>
      <div class="eyebrow">Cliente</div>
      <div class="nome">{e(registro.get('cliente') or '—')}</div>
    </div>
    <div class="right">
      <div class="eyebrow">Seu contato na SuperSonic</div>
      <div class="nome">{e(responsavel)}</div>
      <div class="dim">{e(_CONTATO_EMAIL)} · {e(_CONTATO_TELEFONE)}</div>
    </div>
  </div>

  <div class="route-box">
    <div class="route-top">
      <div class="route-left">
        <div class="eyebrow">Rota</div>
        <div class="cidades">
          <span class="cidade">{e(cidade_origem)}<span class="uf">{e(uf_origem)} · coleta</span></span>
          <span class="arrow">&#8594;</span>
          <span class="cidade">{e(cidade_destino)}<span class="uf">{e(uf_destino)} · entrega</span></span>
        </div>
      </div>
      <div class="route-right">
        <div class="eyebrow" style="color:#AEC2D1;">Frete total</div>
        <div class="total">{_fmt_brl(registro.get('frete_total'))}</div>
        <div class="inclui">Inclui ICMS{' · ' + taxas_resumo if taxas_resumo else ''} sobre a NF · descarga no destino</div>
      </div>
    </div>
    <div class="route-bottom">
      <div><div class="eyebrow">Modal</div><div class="v">Rodoviário</div></div>
      <div><div class="eyebrow">Prazo</div><div class="v">{e(prazo_texto)}</div></div>
      <div><div class="eyebrow">Tipo</div><div class="v">{e(_tipo_orcamento(payload))}</div></div>
    </div>
  </div>

  <div class="secao">
    <div class="secao-titulo">Dados da carga informados</div>
    <table class="carga">
      <tr>
        <th>Valor da NF</th><th>Volumes</th><th>Peso real</th><th>Cubagem</th><th>Peso de cálculo</th><th>Observação</th>
      </tr>
      <tr>
        <td>{_fmt_brl(registro.get('valor_mercadoria'))}</td>
        <td>{qtde_paletes}</td>
        <td>{_fmt_num(entrada.get('peso_kg'))} kg</td>
        <td>{_fmt_num(calc.get('volume_total_m3'), 2)} m³</td>
        <td>{_fmt_num(calc.get('peso_considerado_kg'))} kg</td>
        <td class="obs">{e(observacao_carga)}</td>
      </tr>
    </table>
  </div>

  <div class="secao">
    <div class="secao-titulo">Condições desta cotação</div>
    <div class="cards">
      <div class="card"><div class="t">Inclusos</div><div class="v">ICMS, RCA, GRIS, ADV</div><div class="s">no valor acima</div></div>
      <div class="card"><div class="t">Reentrega</div><div class="v">50% do frete</div><div class="s">se aplicável</div></div>
      <div class="card"><div class="t">Devolução</div><div class="v">100% do frete</div><div class="s">se aplicável</div></div>
      <div class="card"><div class="t">Coleta frustrada</div><div class="v">a combinar</div><div class="s">se aplicável</div></div>
    </div>
    <div class="notas">
      <div><span class="label">Prazo</span> contado em dias úteis a partir do dia seguinte à coleta.</div>
      <div><span class="label">Seguros</span> {taxas_seguro or 'conforme tabela vigente'} incidem sobre o valor da NF e já estão inclusos.</div>
    </div>
    <div class="notas">
      <div><span class="label">Restrições</span> TRT 15% (mín. R$ 28), TZR 20% (mín. R$ 300), TDA 15% (mín. R$ 22), TDE 20% (mín. R$ 285), quando aplicáveis.</div>
      <div><span class="label">Redespacho fluvial</span> 20% sobre o frete, mínimo R$ 40, quando aplicável.</div>
    </div>
    <div class="notas">
      <div><i><b>Embalagem e avaria.</b></i> A mercadoria deve estar devidamente embalada pelo embarcador; sem embalagem adequada a carga pode ser recusada no embarque e a SuperSonic se isenta de responsabilidade por danos decorrentes.</div>
      <div><i><b>Peso e cubagem.</b></i> São responsabilidade do cliente. Divergências apuradas na coleta terão a diferença cobrada conforme tabela. <b>Condições gerais</b> em {e(_EMPRESA_SITE)}/condicoes. Esta cotação não constitui contrato; a contratação se confirma com o aceite por e-mail e emissão do CT-e.</div>
    </div>
  </div>

  <div class="footer">
    <div class="texto">Para contratar, responda este e-mail com o aceite e a NF. <b>Validade: {_VALIDADE_DIAS} dias.</b> Valores sujeitos a alteração de tarifas, pedágios e legislação.</div>
    <a class="btn" href="mailto:{e(_CONTATO_EMAIL)}?subject=Aceite%20{e(codigo)}">Aceitar cotação</a>
  </div>
  <div class="rodape-empresa">
    <div>{e(" · ".join(filter(None, [
        _EMPRESA_RAZAO_SOCIAL,
        f"CNPJ {_EMPRESA_CNPJ}" if _EMPRESA_CNPJ else None,
        _EMPRESA_ENDERECO,
        _EMPRESA_SITE,
    ])))}</div>
    <div>{e(codigo)} · 1/1</div>
  </div>

</body></html>"""


def gerar_pdf_orcamento(registro: dict) -> bytes:
    """Recebe um registro de histórico (como devolvido por
    GET /historico/{codigo}, já com `dados` decodificado) e devolve os
    bytes do PDF gerado a partir do modelo de cotação única."""
    html = _html_orcamento(registro)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome")
            try:
                page = browser.new_page()
                page.set_content(html, wait_until="load")
                pdf_bytes = page.pdf(format="A4", print_background=True)
            finally:
                browser.close()
    except Exception as e:
        raise ExportacaoError(
            "Não foi possível gerar o PDF -- confira se o Google Chrome está instalado no servidor "
            f"(ver README.md, seção de exportação em PDF). Detalhe: {e}"
        ) from e
    return pdf_bytes
