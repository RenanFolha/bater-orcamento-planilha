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
   código).

   **Atualização (sessão seguinte, amostra maior)**: os 2 casos
   inicialmente validados com exatidão eram só 2 pontos — rodando
   `comparar_planilha.py fracionado` com 5 casos reais modernos
   diversos (pesos de 0,35kg a 5.000kg) e checando `EMBARQUE`/`ENTREGA`/
   `COLETA` contra a tabela em ~48 cotações reais (AM→São Paulo,
   pós 01/07/2025), o quadro real é:
   - **EMBARQUE bate em 42/48 (87,5%)** e **ENTREGA em 40/48 (83%)** —
     esses dois componentes seguem a tabela de faixa de peso bem de
     perto.
   - **COLETA só bate em 16/48 (33%)** — na maioria das cotações reais,
     o valor de COLETA real não é o da tabela (frequentemente R$ 50 fixo
     em cargas pequenas, às vezes R$ 0, sem um padrão claro identificado
     ainda). É provavelmente uma taxa mínima/por local de retirada que a
     tabela de faixa de peso sozinha não captura.
   - Pra cargas GRANDES (banda "excedente", acima de 200kg), os 3
     componentes batem exato na maioria dos casos — foi aí que vieram os
     2 casos "perfeitos" da validação inicial (peso 1030kg e 5000kg).
     `frete_final` converge melhor quanto maior o peso: 3,5% de erro no
     caso de 5.000kg, contra até 52% nos casos de poucos kg.

   Conclusão: a tabela de faixa de peso está correta como aproximação
   geral (resultado "ok, mas não exato" pra cargas pequenas/médias), mas
   falta descobrir a regra real de COLETA pra cargas pequenas — pendência
   nova, não investigada a fundo ainda (ver pendências abaixo).
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

- **COLETA não segue a tabela de faixa de peso na maioria das cotações
  pequenas/médias** (só 30,4% de aderência em ~3.300 cotações reais
  pós 17/06/2025, contra 83-87% de EMBARQUE/ENTREGA numa amostra menor)
  — maior gap de precisão do Fracionado hoje.

  **Investigação de acompanhamento (sessão seguinte)**: testando
  `coleta = max(peso_considerado × taxa, R$50)` como taxa LINEAR simples
  (sem faixa nenhuma) em vez da tabela:
  - **Origem AM**: taxa = 0,16 R$/kg bate em **55,4%** (923/1.666) —
    melhor que a tabela, mas tem um segundo grupo relevante (~20%, 335
    cotações) com taxa ~0,20 R$/kg em vez de 0,16. Não achei o que
    diferencia os dois grupos: não é por data (se misturam ao longo de
    todo o período), não é por capital x interior do destino (proporção
    parecida nos dois grupos) — pode ser por cliente específico, tipo de
    veículo negociado, ou outra variável que não está na planilha "Base
    Geral". Não decifrado.
  - **Origem SP**: taxa = 0,20 R$/kg bate em **37,4%** (612/1.636).
  - **Decisão (2026-10-08)**: usuário optou por **manter a tabela de
    faixas atual** (`custos_fracionado_destino`) em vez de trocar pela
    fórmula linear — mesmo sendo uma aderência pior, a fórmula linear
    ainda não está "fechada" (resta o segundo grupo de taxa não
    explicado) pra justificar a troca agora. Fica documentado aqui caso
    alguém queira retomar essa investigação depois.
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
- `comparar_planilha.py fracionado` já usa 5 casos modernos (pós
  17/06/2025, pesos de 0,35kg a 5.000kg, origem SP e AM) — ver nota no
  próprio arquivo pra entender por que `frete_base`/`frete_sem_imposto`/
  `pis_cofins`/`icms` ainda divergem mesmo nesses casos (ordem de
  aplicação da margem + achado da COLETA acima).

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

## Revisão dos achados do Teste_Completo_FTL (sessão seguinte)

`Teste_Completo_FTL_2026_Sistema_vs_Planilha.xlsx` (`Planilhas/`, não
versionado) tem 10 achados rodando 1017 cotações FTL reais de 2026 direto
pelos endpoints (só 9,3% batem em ±5%, ver "Como retomar" original
abaixo). Revisão (2026-10-08): nenhum dos 10 achados foi tocado pelas
correções de ICMS/PIS-COFINS/lotação/fracionado desta sessão (eixos
diferentes) — todos os 10 continuam procedendo. Priorizados por
esforço/dado disponível:

1. **Prazo por rota — IMPLEMENTADO** (achado #7), só pra **Lotação**. Antes:
   `prazo_estimado_dias_uteis` sempre devolvia `SLA.prazo_dias` fixo (5
   dias), não importa a rota. Agora: `_prazo_estimado_dias_uteis` em
   `frete_service.py` — 1 dia base + 1 dia a cada 500km rodados
   (`PRAZO_KM_POR_DIA_ADICIONAL`), mais 5 dias se a rota tem balsa (7 de
   outubro a dezembro, nível do rio baixo —
   `PRAZO_DIAS_EXTRA_BALSA`/`_SECA`). Fórmula vinda direto da observação do
   achado #7 na planilha, validada com as 1017 cotações FTL do próprio
   `Teste_Completo_FTL`. `SLA.prazo_dias` continua cadastrado no banco mas
   não é mais usado pro prazo — fica só como campo legado (não removido,
   pra não quebrar CRUD/telas existentes).

   **Correção (sessão seguinte, 2026-10-08)**: essa fórmula tinha sido
   aplicada também ao **Fracionado** (`calcular_orcamento_fracionado`),
   mas investigando com dados reais de Fracionado (aba "PRAZO" +
   "Base Geral" de `COTAÇÃO SSONIC - 2026.xlsx`, 3.479 cotações
   sem particularidade pós 17/06/2025) ficou claro que o prazo do
   Fracionado **não correlaciona com km rodado** — a coluna `KM` da
   planilha está quase toda vazia (2/3.938) e o prazo real varia só com a
   classificação do destino (UF + capital/interior), às vezes de forma
   contraintuitiva (SP→RO capital ~D+10 vs SP→RR capital ~D+23, SP→SP
   interior ~D+0-3 vs SP→PA interior ~D+10-15). A própria aba "PRAZO" da
   planilha (lookup oficial que ela já usa) só bate 61,7% com o prazo real
   registrado; usando a **moda empírica** por (origem, UF destino,
   capital/interior) o match sobe pra 77,3% (65 de 110 chaves com moda
   dominante em ≥70% dos casos) — mesmo padrão de confiabilidade já
   aceito pra GRIS/ADV/margem/custo de lotação neste projeto.

   Implementado: nova tabela `prazo_fracionado_destino` (mesma chave de
   `custos_fracionado_destino`: origem_tabela + uf_destino +
   capital_interior) e `_prazo_fracionado_destino_aplicavel` em
   `frete_service.py`, usada em `calcular_orcamento_fracionado` com
   fallback pra `_prazo_estimado_dias_uteis` (fórmula por km) quando a
   rota não está cadastrada — `calcular_orcamento` (Lotação) continua só
   com a fórmula por km, inalterada. Populado localmente (dado real, não
   versionado) com 95 chaves (46 AM + 49 SP) via a moda empírica
   calculada a partir da planilha legada. Também corrigido de passagem:
   `ParametrosFrete.__init__` não declarava `custos_fracionado_destino`
   (só existia depois de `.load()`) — qualquer `ParametrosFrete()` montado
   manualmente (ex: em teste) quebrava com `AttributeError` ao cotar
   Fracionado com cidade_origem/destino preenchidos; bug pré-existente,
   nunca exercitado até os novos testes de prazo passarem essas cidades.
2. Tarifas leves/médios SP (achado #3), limites do formulário (achado #8),
   GRIS/ADV/taxa fluvial (achado #9), ICMS indevido por cliente (achado
   #6), balsa Manaus-Belém incompleta (achado #4), roteirização via filial
   (achado #5) e consolidação de carga pequena AM (achado #2, o maior
   esforço — exige modo novo de "rateio de carreta compartilhada") —
   ainda não implementados, na ordem de prioridade discutida na sessão.

## Correções no histórico de orçamento (sessão seguinte, 2026-10-08)

Revisão de código de `routers/historico.py` achou 3 problemas, todos
corrigidos em `routers/historico.py`/`frete_db.py`:

1. **Race condition** em `PUT /historico/{id}/pedagio` e `/recalcular` —
   leitura e escrita do `dados_json`/`frete_total` não eram atômicas (duas
   edições quase simultâneas no mesmo registro podiam se sobrescrever
   silenciosamente). Corrigido com controle de concorrência otimista:
   `atualizar_pedagio_historico`/`atualizar_recalculo_historico` recebem o
   `dados_json` que o router leu antes de calcular o novo valor
   (`dados_json_esperado`) e comparam com o valor atual no banco,
   imediatamente antes do `UPDATE`, na mesma transação — se mudou nesse
   meio tempo, rejeita com `ConflitoIntegridade` → HTTP 409 em vez de
   sobrescrever.
2. **`frete_total` podia ficar negativo** em `atualizar_pedagio` — corrigir
   um pedágio antigo super estimado pra um valor bem menor podia zerar ou
   inverter o sinal do frete total salvo. Agora tem piso em 0
   (`max(0.0, ...)`, mesmo padrão de `ajuste_piso_markup`).
3. **`listar_historico` buscava a coluna `dados_json` inteira** (snapshot
   completo, vários KB por linha) só pra descartar em Python a cada `GET
   /historico`. `db.listar_orcamentos_historico()` agora faz `SELECT` só
   das colunas usadas na listagem.

Commit `c69c989` (pushado pra `bater/main`) tem as duas coisas: essas 3
correções do histórico + a implementação do prazo do Fracionado por
destino (ver seção acima).

## Divergências achadas vs "Sistema de Precificação" (manual oficial +
## contratos + tabelas de custo, sessão seguinte, 2026-10-08)

Pasta local `Sistema de Precificação/` (não versionada, mesma razão de
`Planilhas/` — adicionada ao `.gitignore`) tem o manual oficial
("Manual Precificação Logistica Terrestre_Grupo IS_v20.docx"), contratos
de balsa (Chibatão/Belnave/Unirios), tabelas de custo de transferência por
região e a tabela de frete agregado reajustada de junho/2026. Comparação
sistemática contra `frete_service.py`/`frete.db`, por impacto:

1. **Tabela de lotação SP desatualizada** — `custos_lotacao_destino`
   (ex: SP→Manaus R$27.516,60) está 29-53% ACIMA da
   `TABELA_DE_FRETE_JUNHO_2026` vigente (SP→Manaus R$19.038,00). Pode ser
   diferença de escopo (custo total vs só trecho carreteiro) — não
   confirmado, vale conferir antes de decidir se precisa reextrair.
2. **Prazo do Fracionado** — já corrigido (ver seção acima).
3. **Peso excedente em Carreta — investigado, mantido R$220/t (sessão
   seguinte, 2026-10-08)**. Manual diz R$200,00/tonelada acima de 18t;
   `veiculos.valor_tonelada_excedente` da Carreta está em R$220,00/t
   (10% acima). Investigado com o mesmo método das outras validações
   (extrair cotações reais da Base Geral, filtrar particularidade e
   corte de 17/06/2025), mas a amostra é pequena e ruidosa demais pra
   decidir: de 347 cotações reais de Lotação acima de 18t, 291 (84%)
   estão em rotas já cadastradas em `custos_lotacao_destino`, onde o
   peso excedente nunca é cobrado hoje (custo da tabela substitui
   `custo_km + custo_peso_excedente` por completo) -- a questão só
   importa pros 16% restantes. Dessas, só 46 ficaram "limpas", e nem
   pares na mesma rota exata (taxa implícita variando de R$109/t a
   R$632/t entre datas diferentes) nem regressão linear (R² entre 0,009
   e 0,082, ou seja, peso excedente não explica a variação do
   custo_total nessa amostra) deram um sinal confiável em nenhuma
   direção. **Decisão do usuário: manter R$220/t por enquanto** --
   sem dado confiável pra justificar a troca pro R$200 do manual.
4. **RCA (Fracionado) — IMPLEMENTADO (sessão seguinte, 2026-10-08)**.
   Revisão inicial achou que RCA "não existe no sistema", mas na verdade
   já existia de um jeito diferente do manual: cadastrado em
   `taxas_regionais` (não `taxas_adicionais`), 0,05% (não 0,12%), e só se
   aplicava quando origem/destino era exatamente Manaus ou Belém (não em
   toda cotação de Fracionado) — aparecia no resultado como "Taxa fluvial
   (RCA)". Decisão do usuário: generalizar como GRIS/Ad Valorem em vez de
   só corrigir o %. Implementado: `_NOME_TAXA_RCA` em `frete_service.py`,
   `rca_pct` editável por orçamento (igual `gris_pct`/`ad_valorem_pct`,
   mesma validação de piso/tipo fixo), aplicado via
   `_taxas_adicionais_aplicadas(...)`. Banco: removidas as 2 linhas
   antigas de `taxas_regionais` (Manaus/Belém 0,05%) e inserida 1 linha
   nova em `taxas_adicionais` ("RCA", percentual, 0,12%) -- dado local,
   não versionado, mesma política de GRIS/Ad Valorem. Frontend
   (`index.html`/`assets/app.js`): campo `rca_pct` no formulário
   Fracionado, linha própria no resultado ("RCA"), e o rótulo genérico de
   `taxas_regionais` (que dizia "Taxa fluvial (RCA)" nos dois formulários)
   corrigido pra "Taxas regionais" (mecanismo continua existindo, só não é
   mais usado pra nada hoje já que as 2 linhas foram removidas).

   **Extensão (mesma sessão): RCA também na Lotação.** Pedido explícito
   do usuário -- decisão consciente de divergir do manual (que descreve
   RCA só pro Fracionado; a Lotação tem "Seguro Rodoviário" com
   composição diferente, 0,07%+0,03%, nunca implementada). Removido o
   parâmetro `incluir_rca` de `_taxas_adicionais_aplicadas` (RCA passou a
   ser tratado exatamente como GRIS/Ad Valorem, sem escopo por modal);
   `calcular_orcamento` ganhou `rca_pct` com a mesma validação de piso/
   tipo fixo. Frontend: campo `rca_pct` e linha de resultado "RCA"
   também na tela de Lotação. Testes: 6 no total em
   `tests/test_frete_service.py` (override, piso e default cadastrado,
   repetidos pros dois modais).
5. Isenção de ICMS sul de MG, transbordo (tarifa reduzida Belém→Sudeste),
   lotação curta em SP (Valinhos/Ribeirão Preto), subcontratação sem
   ICMS, diária de entrega em Belém/Macapá, custos adicionais
   (ajudante/conferente/empilhadeira por filial) — **não implementados**,
   a maioria já conhecida como pendência dos achados do
   `Teste_Completo_FTL` (achados #6 e #8).
6. Valores de balsa no banco (`taxas_balsa`) já estão mais altos que os do
   manual, citando os próprios contratos reajustados de 2026 (Carta
   140/2026-BEL, propostas Belnave/Unirios de abril/2026) — parecem ter
   sido atualizados numa sessão anterior direto desses PDFs, não é uma
   divergência real.

Nenhuma dessas foi implementada nesta sessão (fora o prazo do
Fracionado) — fica como lista de pendências priorizada.

## Como retomar

1. Confirmar que `Planilhas/COTAÇÃO SSONIC - 2026.xlsx` e a pasta
   `Sistema de Precificação/` existem localmente (nenhuma versionada).
2. Rodar `comparar_planilha.py` pra ver o estado atual.
3. Rodar a suíte (`pytest tests/ -q`) antes de qualquer mudança nova, pra
   ter uma baseline (547 passed, 4 skipped nesta sessão).
4. Decidir por qual pendência seguir. Fracionado SP/AM já calcula e o
   custo bate exato (ver seção acima) — falta GRIS/ADV/fluvial por UF,
   PA/outras origens, e separadamente há os achados do `Teste_Completo_
   FTL_2026_Sistema_vs_Planilha.xlsx` e as divergências do "Sistema de
   Precificação" (ambas seções acima) — prazo por rota e RCA do
   Fracionado já implementados, peso excedente de Carreta investigado e
   mantido em R$220/t (sem dado confiável pra trocar), restam tarifas
   SP, limites de formulário, ICMS por cliente, balsa, roteirização,
   consolidação de carga AM e a tabela de lotação SP possivelmente
   desatualizada.
