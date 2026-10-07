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

## Diferenças de código vs o repositório principal (Cota-o-SSonic)

Este worktree está **5 commits à frente** da branch `main` do repo
principal (`2d98598`, `dc55c2f`, `27417cc`, `2bcf767`, `cef1501` — ver
`git log main..worktree-bater-orcamento-planilha` com os dois worktrees
lado a lado). Resumo das diferenças de cálculo (detalhadas nos itens 1-5
abaixo), gerado via `git diff` entre as duas branches — tem uma planilha
com essa comparação, destacada por tipo, enviada ao usuário em
2026-10-07 (`Diferencas_Calculo_vs_CotaSSonic.xlsx`, não versionada):

- **ICMS**: invertido — era soma simples por fora, virou gross-up "por
  dentro" (item 1).
- **PIS/COFINS**: invertido — era gross-up "por dentro", virou % simples
  por fora (item 2). Ou seja, as fórmulas de ICMS e PIS/COFINS estavam
  **trocadas** entre si no projeto original.
- **Lotação (FTL)**: funcionalidade nova — tabela `custos_lotacao_destino`
  por rota (item 5).
- **Fracionado (LTL)**: funcionalidade nova — de 100% quebrado
  (`FreteConfigError` sempre) pra funcional em SP/AM via
  `custos_fracionado_destino` (seção própria abaixo).

**Ressalva importante — correção de % é dado, não código**: os valores de
GRIS (0,05%→0,15%), Ad Valorem (0,047%→0,35%) e PIS/COFINS (9,25%→3%)
citados nos itens 2/3 abaixo foram corrigidos **direto no `frete.db`
local deste worktree** (tabelas `taxas_adicionais` e
`aliquota_pis_cofins`), não no seed default de `frete_db.py` — o seed
continua com os mesmos valores de exemplo (0,30%/0,50%) nos dois
projetos. **Quem pegar só o código deste repo sem copiar o `frete.db`
local leva as correções de fórmula (ICMS/PIS-COFINS/lotação/fracionado)
mas NÃO leva nenhuma das correções de percentual** — são dado em runtime,
não fazem parte do código versionado.

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

   **Investigação de acompanhamento (sessão seguinte)**: os 3 casos de
   lotação que `comparar_planilha.py` mostra "divergindo muito" (Macapá/AP
   linha 10, Tocantinópolis/TO linha 42, Cajamar→Belém linha 117) **não são
   rota faltando em `custos_lotacao_destino`** — as 3 rotas já estavam
   cadastradas e `frete_base` do sistema bate exato com
   `custo_tabela + 33,10` nos três. A divergência tem duas causas
   diferentes, confirmadas direto na planilha:
   - Macapá (02/06/2025) e Tocantinópolis (09/06/2025) são **anteriores ao
     corte de 17/06/2025** (regime antigo, `MARKUP=0` na planilha;
     Tocantinópolis inclusive tem GRIS/Ad Valorem zerados naquela cotação
     específica) — mesma categoria "não replicável" do item acima, não
     bug.
   - Cajamar→Belém (26/06/2025) é moderna e o custo bate, mas essa
     cotação usou GRIS 0,2%/Ad Valorem 0,4% em vez do padrão nacional
     (0,15%/0,35%). Checado em 139 cotações reais de lotação pra UF
     destino PA: 0,15%/0,35% é a moda (76/139, 55%), 0,2%/0,4% é a segunda
     mais comum (31/139, 22%) — não é uma regra fixa de UF, é negociação
     por cliente/cotação, mesma natureza do achado do item 4 (margem) —
     já coberto pelos campos `gris_pct`/`ad_valorem_pct` por orçamento
     quando o valor negociado for conhecido, não dá pra virar regra fixa
     por UF.

   Conclusão: a tabela de custo de lotação está completa e correta pros 7
   casos de teste — nenhuma rota falta cadastrar.

6. **Frontend** (`assets/app.js`, `index.html`) — labels/tooltips de
   ICMS/PIS-COFINS corrigidos (estavam descrevendo a fórmula antiga,
   exatamente invertida).

7. **Testes** — suíte completa ajustada (539 passed, 4 skipped). Dois
   testes de integração que validavam "alíquota ≥100% dá erro 500"
   migraram de PIS/COFINS pra ICMS (a validação técnica migrou porque só o
   gross-up tem risco de divisão por zero).

## Fracionado (LTL) — investigado e parcialmente implementado (sessão seguinte)

Antes disso o Fracionado falhava 100% das vezes (`FreteConfigError`, nenhuma
faixa cadastrada). Investigação (mesmo método do item 5: extrair e analisar
dados reais, não assumir):

1. **Custo** (`COLETA+EMBARQUE+ENTREGA`) vem de 3 tabelas por faixa de peso
   fixa (10/20/30/50/70/100/150/200kg + R$/kg excedente acima de 200kg),
   uma por UF+capital/interior do destino, extraídas das abas "TB
   FRACIONADO - CUSTO (SP)" e "TB FRACIONADO - CUSTO (AM)" (a aba "(PA)"
   existe mas está toda zerada na planilha — não extraída, origem PA do
   Fracionado não tem custo real cadastrado lá). Nova tabela no banco:
   `custos_fracionado_destino` (chave: origem_tabela + uf_destino +
   capital_interior + componente), implementada em
   `frete_service._custo_fracionado_destino_aplicavel` — quando a rota
   não está coberta (faltam dados dos 3 componentes), cai no fallback
   antigo de `faixas_peso_fracionado`/`faixas_distancia_fracionado`
   genérico (que continua vazio hoje, então ainda falha fora de SP/AM).
   Populado localmente (dado real, não versionado) com 111+87 linhas
   (37 destinos SP × 3 componentes + 29 destinos AM × 3). Classificação
   capital/interior usa a lista fixa `CAPITAIS_BR` em `frete_service.py`
   (extraída da aba "Capitais" — inclui região metropolitana quando a
   planilha trata como capital, ex: Guarulhos/Barueri/Osasco em SP,
   Ananindeua em PA). Bahia tem 3 faixas na planilha (CAPITAL/INTERIOR
   I/INTERIOR II); como só distinguimos capital x resto, interior da
   Bahia cai em "INTERIOR I" por aproximação (limitação documentada no
   código). **Validado com exatidão** em 2 casos reais modernos (SP→Manaus
   e Manaus→São Paulo): `custo_tabela_fracionado_destino` bate exato com
   a coluna CUSTO TOTAL da planilha.
2. **Margem/preço de venda**: não precisou de lógica nova — o mecanismo
   que já existe no código (`MARGEM_LUCRO_PADRAO=40`, `MARKUP_MINIMO=1.4`
   em `_aplicar_margem_lucro`/`_aplicar_piso_markup`, os mesmos usados em
   lotação) já é a regra vigente da planilha pro Fracionado também —
   confirmado batendo os valores de "Margem" (quase sempre 0,4) e
   "MARKUP" (~1,4) das cotações reais pós 17/06/2025 com essas duas
   constantes. Mesma ressalva do item 5 (ordem de aplicação): a planilha
   embute a margem direto no "frete_base" dela, o sistema aplica em
   cascata separado — bate no frete final, não nos campos intermediários.
3. **Cotações anteriores a 17/06/2025** (mesmo corte do PIS/COFINS): usam
   fórmula antiga (sem o conceito de MARKUP, margem variável tipo 0,2/0,3)
   — decisão consciente de não replicar, mesma política do item 5.

### Pendências / não implementado ainda (Fracionado)

- GRIS/Ad Valorem/Taxa Fluvial do Fracionado variam por UF/capital-interior
  na planilha (ex: AM tem GRIS 0,2%/ADV 0,6%/fluvial 1%, mas o sistema usa
  só o % nacional cadastrado em Tabela de Preços, sem fluvial nenhum) —
  mesma limitação já aceita pra lotação (item 3), não implementada aqui
  também.
- Origem PA do Fracionado: aba de custo existe mas está zerada na
  planilha — não há dado real pra extrair.
- Outras origens de Fracionado (fora SP/AM): não existem abas de custo
  pra extrair.
- Bahia: interior não diferencia "INTERIOR I" de "INTERIOR II" (usa
  sempre a faixa I).
- `comparar_planilha.py` ainda só tem os 6 casos antigos (pré-corte) —
  não foram trocados por casos modernos; a validação exata foi feita à
  parte (ver nota no próprio arquivo).

## Outras pendências / não implementado ainda

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
4. Decidir por qual pendência seguir. Fracionado SP/AM já calcula e o
   custo bate exato (ver seção acima) — falta GRIS/ADV/fluvial por UF,
   PA/outras origens, e separadamente há o achado do `Teste_Completo_
   FTL_2026_Sistema_vs_Planilha.xlsx` (em `Planilhas/`, não versionado):
   rodando 1017 cotações FTL reais de 2026 direto pelos endpoints, só
   9,3% batem em ±5% — achados maiores: consolidação de carga pequena em
   AM, tarifas de veículos leves/médios em SP abaixo do praticado, regra
   de balsa Manaus-Belém incompleta, prazo sempre fixo "5 dias úteis".
