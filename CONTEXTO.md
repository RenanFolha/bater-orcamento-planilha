# Contexto: bater orçamento do sistema com a planilha legada

Este projeto é um **worktree git** (branch `worktree-bater-orcamento-planilha`)
originado do repositório principal `Cota-o-SSonic` (frete.folha), movido pra
fora dele (`git worktree move`) pra trabalhar isolado.

## Objetivo

Fazer os orçamentos calculados pelo sistema (`frete_service.py`) baterem com
os valores históricos da planilha legada `Planilhas/COTAÇÃO SSONIC - 2026.xlsx`
(aba "Base Geral") — a planilha é a fonte de verdade usada pela empresa antes
do sistema existir, e tem a lógica de cálculo "correta" (vigente) que o
sistema deveria replicar.

A planilha **não está versionada** (está no `.gitignore`, contém dados reais
de preço/cliente) — fica só localmente em `Planilhas/`. Se não existir nesse
caminho, pedir pro usuário a cópia de novo.

## Ambiente de teste

`comparar_planilha.py` (raiz do projeto) é a ferramenta criada pra essa
investigação: extrai casos reais da planilha (inputs + valores esperados) e
roda o mesmo cálculo no sistema, comparando campo a campo.

```
.venv/Scripts/python.exe comparar_planilha.py              # todos os casos
.venv/Scripts/python.exe comparar_planilha.py lotacao       # só lotação (FTL)
.venv/Scripts/python.exe comparar_planilha.py fracionado    # só fracionado (LTL)
```

Não é teste automatizado de regressão (não é pytest) — é ferramenta de
desenvolvimento, pra rodar manualmente a cada ajuste. Tem 7 casos hoje (6
lotação de Manaus/AM + 1 de São Paulo/SP), documentados no próprio arquivo.

## O que já foi corrigido (commit `2d98598`)

Investigação feita extraindo e analisando centenas de linhas reais da
planilha (não só exemplos pontuais) pra achar o padrão real, não assumir:

1. **ICMS** (`frete_service._aplicar_icms`) — era soma simples por fora,
   agora é gross-up "por dentro" (`frete / (1 - aliquota/100)`), que já era
   a intenção documentada no comentário do campo `AliquotaIcms.aliquota`
   mas a implementação estava errada.

2. **PIS/COFINS** (`frete_service._aplicar_pis_cofins`) — era 9,25%
   gross-up, agora é **3% percentual simples**. Achado extraindo 400 linhas:
   332 de 333 casos com PIS/COFINS bateram exatamente em 3,00% sobre o
   `frete_sem_imposto`. Também achei que é uma regra vigente desde
   **17/06/2025** (antes disso a planilha não cobrava PIS/COFINS separado).
   Valor cadastrado no banco (`aliquota_pis_cofins`) atualizado de 9,25%
   pra 3%.

3. **GRIS/Ad Valorem** (tabela `taxas_adicionais` no banco) — eram valores
   de exemplo (0,05% / 0,047%, nunca ajustados), corrigidos pra **0,15% /
   0,35%** — a moda real confirmada em 1749 linhas de lotação, estável e
   cada vez mais dominante nos meses recentes (>90% de aderência). Exceções
   conhecidas e não implementadas: Pernambuco usa 0,2%/0,45%, Alagoas e
   Piauí usam Ad Valorem 0,4% — podem ser digitadas por orçamento
   (`gris_pct`/`ad_valorem_pct`) quando necessário.

4. **Margem de lucro** — investigado e **descartado**: não é fixa por modal
   como um relatório inicial (baseado em amostra pequena) supôs. É
   negociação caso a caso, varia muito mesmo dentro do mesmo modal/dia. 40%
   é a moda mais frequente em todos os modais (50-75% dos casos) — o
   `MARGEM_LUCRO_PADRAO = 40` fixo do sistema já é a melhor aproximação
   possível. Não foi alterado.

5. **Tabela de custo de lotação por destino** (`custos_lotacao_destino`,
   nova tabela no banco) — o maior item estrutural. A planilha usa uma
   tabela de custo pré-negociado por (origem, UF+cidade destino), não
   tarifa_km×distância. Implementado: `_custo_lotacao_destino_aplicavel`
   busca o custo cadastrado; se encontrado, substitui
   `custo_km + custo_peso_excedente` por
   `custo_tabela + TAXA_FIXA_LOTACAO_TABELA (33,10)`, SEM aplicar
   multiplicador de categoria/transporte/SLA (o valor já é o custo
   operacional completo, igual na planilha). Populado localmente (não
   versionado, é dado) com **175 rotas**: 101 Manaus/AM, 68 São Paulo/SP, 6
   Paraná/PR, extraídas das abas `TB LOTAÇÃO - CUSTO (SP/AM/PR)`.
   **Fórmula validada com precisão exata** em 7 casos reais de 2 origens
   diferentes: `frete_base = custo_tabela + 33,10` bate exato quando
   comparado corretamente (a planilha multiplica a margem dentro do
   próprio frete_base; o sistema soma a margem depois, separadamente —
   são modelos diferentes que convergem quase exato, não comparar os dois
   campos diretamente).

   **Resultado**: nos casos "modernos" (pós 17/06/2025, margem/GRIS/Ad
   Valorem no padrão), o `frete_final` bate em ~1% — contra 36-65% de erro
   antes de toda essa investigação.

6. **Frontend** (`assets/app.js`, `index.html`) — labels/tooltips de
   ICMS/PIS-COFINS corrigidos (estavam descrevendo a fórmula antiga,
   exatamente invertida).

7. **Testes** — suíte completa ajustada (539 passed, 4 skipped). Dois
   testes de integração que validavam "alíquota ≥100% dá erro 500"
   migraram de PIS/COFINS pra ICMS (a validação técnica migrou porque só o
   gross-up tem risco de divisão por zero).

## Pendências / não implementado ainda

- **Fracionado (LTL)**: nenhuma faixa de peso cadastrada em Tabela de
  Preços → Fracionado hoje — todo caso de fracionado falha com
  `FreteConfigError` antes de calcular qualquer coisa. Não investigado a
  fundo ainda.
- **Aba "TB LOTAÇÃO - DIVERSOS"**: estrutura diferente das outras (origem
  variável linha a linha, não fixa por filial/UF) — não cadastrada.
- **Outras origens de lotação** (fora SP/AM/PR): não extraídas.
- **Resíduo de ~1%** no frete_final dos casos modernos: vem da margem ser
  multiplicativa na planilha (`(custo+33,1)×(1+margem)`) e aditiva no
  sistema (soma separada depois). Fechar isso exigiria mudar a mecânica de
  aplicação de margem em todo o sistema (não só lotação) — avaliado como
  esforço desproporcional ao ganho, não feito.
- Decisão consciente: casos anteriores a 17/06/2025 (fórmula antiga, com
  um fator `/0,86` que já não existe mais na planilha) não são replicados
  — o sistema reflete a regra vigente, não a histórica.

## Como retomar

1. Confirmar que `Planilhas/COTAÇÃO SSONIC - 2026.xlsx` existe localmente
   (não versionado).
2. Rodar `comparar_planilha.py` pra ver o estado atual.
3. Rodar a suíte (`pytest tests/ -q`) antes de qualquer mudança nova, pra
   ter uma baseline.
4. Decidir por qual pendência seguir (fracionado é provavelmente a próxima
   mais impactante, já que hoje falha 100% das vezes).
