# Sistema de Orçamento de Frete

**Desenvolvedor Chefe:** RenanFolha

Aplicação local que calcula o frete a partir de regras cadastradas num
banco SQLite (`frete.db`) — sem depender de planilha. Inclui filiais
pré-cadastradas, cálculo automático de distância por endereço e taxa de
coleta quando a carga é retirada direto no cliente.

## Como rodar

1. Instale as dependências (Python 3.10+):
   ```bash
   pip install -r requirements.txt
   ```

2. Suba a aplicação:
   ```bash
   python main.py
   # ou: uvicorn main:app --reload --port 8000
   ```

   Na primeira execução, o arquivo `frete.db` é criado automaticamente
   na mesma pasta, já com dados de exemplo (faixas de peso, distância,
   coleta, categorias, transportes, SLAs e as 4 filiais).

3. Acesse a tela no navegador: `http://localhost:8000/`

## Login e usuários

Na primeira execução o sistema cria um usuário administrador padrão:

- **Usuário:** `admin`
- **Senha:** `admin123`

**Troque essa senha assim que possível** — clique em "Trocar senha" no
rodapé do menu lateral depois de entrar.

Existem dois papéis:

| Papel | Pode acessar |
|---|---|
| **Administrador** | Novo Orçamento, Histórico, Tabela de Preços e Configurações (inclusive gerenciar outros usuários) |
| **Usuário comum** | Novo Orçamento e Histórico |

Gerar um orçamento (tela inicial) **não exige login** — qualquer um
pode calcular um frete. Mas salvar esse orçamento no histórico, ver o
histórico, editar a Tabela de Preços e acessar Configurações exigem
estar logado. Administradores gerenciam os usuários pela tela
Configurações → "Usuários" (criar, trocar papel, ativar/desativar,
redefinir senha ou excluir — sempre precisa sobrar pelo menos um
administrador ativo no sistema).

## ⚠️ Antes de usar de verdade: edite os endereços das filiais

As filiais vêm cadastradas com endereços genéricos ("Centro, Campinas,
SP, Brasil" etc.), só para o sistema funcionar de primeira. **Edite com
o endereço completo e real de cada filial** (rua, número, bairro,
cidade, UF) para que o cálculo de distância seja preciso — veja abaixo
como editar.

## Editando os dados (preços, filiais, faixas etc.)

Sem planilha — agora tudo fica no banco `frete.db`. Para editar:

1. Baixe o [DB Browser for SQLite](https://sqlitebrowser.org/) (gratuito).
2. Abra o arquivo `frete.db` que está na pasta do projeto.
3. Vá na aba **"Browse Data"**, escolha a tabela e edite as células
   normalmente (duplo clique).
4. Clique em **"Write Changes"** para salvar.
5. Com a API rodando, chame para aplicar as mudanças sem reiniciar:
   ```bash
   curl -X POST http://localhost:8000/admin/reload
   ```

### Tabelas do banco

| Tabela                  | O que guarda                                             |
|--------------------------|-----------------------------------------------------------|
| `veiculos`               | Veículos, tarifa/km, peso incluso e valor/kg excedente    |
| `taxas_adicionais`       | Taxas nomeadas (GRIS, Ad Valorem etc.), fixas ou %        |
| `coleta_cidades_fixas`   | Preço fixo de coleta por rota (filial de origem → cidade(s) do cliente, uma ou várias separadas por vírgula) + veículo (sobrepõe a faixa por km)|
| `taxas_regionais`        | Taxas cobradas quando a cidade de origem OU destino bate com uma cidade cadastrada (ex: zona franca de Manaus), fixas ou % |
| `taxas_balsa`            | Custo de travessia de balsa por rota **direcional** (cidade de origem → cidade de destino) + veículo — ida e volta podem ter valores diferentes, cadastre uma linha pra cada sentido |
| `prioridades_rota`       | Rota **direcional** (estado de origem, UF → cidade de destino) que não tem acesso direto e precisa passar por uma filial cadastrada antes do destino (ex: Manaus sempre via Belém) — a distância do frete passa a ser a soma das duas pernas |
| `faixas_coleta`          | Faixas de distância da taxa de coleta (retirada no cliente)|
| `categorias`             | Categorias de produto e multiplicador                     |
| `transportes`            | Métodos de transporte, multiplicador e fator de cubagem   |
| `slas`                   | Níveis de serviço, multiplicador e prazo                  |
| `filiais`                | Nome, endereço e coordenadas (lat/lon) de cada filial      |
| `faixas_peso` / `faixas_distancia` | Tabelas antigas (tipo de frete) — mantidas por compatibilidade, não usadas no cálculo |

> As colunas `latitude`/`longitude` da tabela `filiais` são
> preenchidas automaticamente pela API na primeira vez que a filial é
> usada num cálculo (fica em cache, não precisa geocodificar de novo).
> Se você editar o endereço de uma filial, apague os valores de
> `latitude`/`longitude` daquela linha para forçar a busca de novo.

## Tabela de Preços (editar direto pela tela)

O menu lateral tem uma página **"Tabela de Preços"** onde dá pra ver e
editar todos os valores sem precisar do DB Browser: veículos, taxas
adicionais, coleta com preço fixo por cidade, faixas de coleta por km,
categorias, transportes e SLAs.

Cada tabela tem um botão **💾 Salvar** e **🗑 Excluir** por linha, e uma
linha extra no final pra adicionar um novo registro (**+ Adicionar**).
Qualquer mudança já vale na hora no cálculo do frete — não precisa
chamar `/admin/reload` manualmente, a própria tela faz isso por trás
dos panos a cada salvamento.

O DB Browser continua funcionando normalmente também, se preferir editar
por lá — os dois caminhos mexem no mesmo banco `frete.db`.

### Endpoints de administração (CRUD)

Para cada uma das tabelas abaixo existem os quatro verbos:
`GET /admin/{recurso}` (listar, com `id`), `POST /admin/{recurso}`
(criar), `PUT /admin/{recurso}/{id}` (editar) e
`DELETE /admin/{recurso}/{id}` (excluir):

- `/admin/filiais`
- `/admin/veiculos`
- `/admin/taxas-adicionais`
- `/admin/taxas-regionais`
- `/admin/taxas-balsa`
- `/admin/coleta-cidades-fixas`
- `/admin/faixas-coleta`
- `/admin/categorias`
- `/admin/transportes`
- `/admin/slas`
- `/admin/transportadoras-terceirizadas`

Nomes duplicados (filial, veículo, categoria, transporte, SLA repetido,
ou a mesma combinação de rota/cidade nas tabelas de coleta e taxa
regional) retornam `409 Conflict` com uma mensagem explicando o
problema. Todas essas rotas exigem login como administrador (ver
[Autenticação](#autenticação) abaixo).

## Cálculo do frete por veículo

O frete principal é calculado com base no **veículo** escolhido nas
abas do topo da tela (Carreta, Truck/Toco, VUC, Van/HR, Caminhonete —
edite/adicione veículos na Tabela de Preços). Cada veículo tem:

- **Tarifa por km** (R$/km × distância percorrida)
- **Valor por tonelada excedente** (sobretaxa por tonelada de sobrepeso além do "até" do veículo — só cobra quando a carga ultrapassa até o maior veículo cadastrado, caso em que o sistema usa esse veículo mesmo assim)

```
peso_excedente_kg = max(peso_considerado - veiculo.até, 0)
frete_base = (tarifa_km × distância) + (peso_excedente_kg / 1000 × valor_tonelada_excedente)
frete_ajustado = frete_base × multiplicador_categoria × multiplicador_transporte × multiplicador_sla
```

Em cima disso somam-se:
- **Taxas Adicionais** — lista editável (GRIS, Ad Valorem, Taxa de
  Localidade etc.), cada uma fixa em R$ ou % do valor da mercadoria.
- **Taxas Regionais** — como as adicionais, mas só entram quando a
  cidade de origem ou destino do frete bate com uma cidade cadastrada
  (ex: taxa de zona franca em Manaus). Ver `/admin/taxas-regionais`.
- **Taxa de Balsa** — custo de travessia quando a rota **cidade de
  origem → cidade de destino** (nessa ordem exata) e o veículo baterem
  com uma linha cadastrada em `/admin/taxas-balsa`, fixo em R$ ou % do
  valor da mercadoria. É direcional: a volta (destino → origem) só
  aplica se tiver a própria linha cadastrada — o preço da travessia pode
  ser diferente em cada sentido.
- **Prioridade de Rota** — quando a rota **estado de origem (UF) → cidade
  de destino** bate com uma linha cadastrada em
  `/admin/prioridades-rota` (ex: destino Manaus não tem acesso
  rodoviário direto e sempre passa por uma filial em Belém antes), a
  distância calculada em `/geo/distancia` deixa de ser a rota direta e
  passa a ser a soma origem → filial de escala + filial de escala →
  destino. Também aceita `"*"` em estado e destino, com a mesma regra de
  especificidade da Taxa de Balsa.
- **Distância Fixa por Corredor** — quando a rota **cidade de origem →
  cidade de destino** bate com uma linha cadastrada em
  `/admin/distancias-fixas`, usa esse valor de km no lugar do cálculo
  automático (rodoviário via OSRM/Google) — útil quando a rota real
  usada na prática (ex: com travessia de balsa) é bem mais curta que a
  rota 100% rodoviária que o serviço de mapa calcularia. Vale tanto pra
  rota direta quanto pra cada perna de uma Prioridade de Rota. Mesma
  regra de direção/curinga/especificidade da Taxa de Balsa.
- **Taxa de coleta** — quando há retirada no cliente (frota própria,
  veja abaixo) ou o valor combinado com a transportadora, quando a
  coleta é terceirizada.
- **Entrega terceirizada** — valor combinado com a transportadora,
  quando a entrega final não é feita pela frota própria.
- **Pedágio** — na ordem de prioridade: (1) catálogo de praças cadastrado
  (ver abaixo), (2) estimativa do Google Maps, (3) digitado manualmente.
- **Manutenção e retorno vazio** — `tarifa_km_manutencao × (distância +
  distância_coleta + distância_retorno)` (sobre toda distância que a
  frota própria roda: ida com carga, coleta no cliente — quando não é
  terceirizada — e volta vazia) e `tarifa_km_retorno × distância_retorno`
  (só o retorno, do destino até a filial mais próxima), ambos
  configuráveis por veículo — custos operacionais, não entram nos
  multiplicadores de categoria/transporte/SLA.

```
frete_total = frete_ajustado + coleta + entrega_terceirizada
            + taxas_adicionais + taxas_regionais + taxa_balsa + pedagio
            + manutencao + retorno_vazio
```

> As tabelas antigas de "tipo de frete" (`faixas_peso`/`faixas_distancia`)
> continuam existindo no banco por compatibilidade, mas não são mais
> usadas no cálculo — o veículo assumiu esse papel.

### Pedágio: catálogo de praças por número de eixos

Além da estimativa genérica do Google Maps, dá pra cadastrar um catálogo
real de praças de pedágio (rodovia, concessionária, preço por número de
eixos do veículo — igual às tabelas publicadas pelas concessionárias) e
ligar cada corredor (cidade de origem → cidade de destino) às praças que
ele atravessa:

- **Veículos** ganham um campo **Nº de eixos** (`/admin/veiculos`) — é
  ele que decide qual coluna de preço usar em cada praça. Veículo sem
  número de eixos cadastrado (0) fica de fora do cálculo automático.
- **Praças de Pedágio** (`/admin/pracas-pedagio`) — catálogo com nome,
  rodovia, concessionária e um preço por número de eixos (2 a 9). Pode
  ser cadastrado manualmente na tela ou importado em lote via CSV
  (`POST /admin/pracas-pedagio/importar-csv`, mesmo formato publicado
  pelas concessionárias — uma linha por praça, uma coluna por número de
  eixos; faz upsert por nome+rodovia, então reimportar uma tabela
  atualizada só ajusta os valores que mudaram).
- **Pedágios por Rota** (`/admin/pedagios-rota`) — liga um corredor
  direcional (cidade_origem → cidade_destino, aceita `"*"` como curinga,
  mesma regra de especificidade da Taxa de Balsa) a uma ou mais praças
  do catálogo. Um corredor normalmente atravessa mais de uma praça — o
  valor final do pedágio é a **soma** de todas as praças do corredor
  mais específico que bater com a rota.

Quando `/geo/distancia` já sabe o veículo (peso/paletes/transporte
informados) e existe um corredor cadastrado pra aquela rota, o pedágio
calculado a partir do catálogo **sobrepõe** a estimativa do Google Maps
— é mais preciso, porque vem do preço real da concessionária pro
veículo escolhido, não de uma estimativa genérica. Sem corredor
cadastrado, cai de volta pra estimativa do Google (ou fica em branco,
editável manualmente, sem `GOOGLE_MAPS_API_KEY`).

## Como funciona o frete com filial/retirada/entrega

O formulário tem dois seletores independentes:

- **Origem**: "Filial" (escolhe uma das cadastradas) ou "Retirada no
  cliente" (digita o endereço onde a carga será retirada — o sistema
  acha sozinho a filial cadastrada mais próxima e calcula a taxa de
  coleta entre ela e o endereço).
- **Destino**: "Filial" (cliente retira na filial) ou "Entrega no
  cliente" (digita o endereço de entrega).

O botão "Calcular distância" resolve tudo isso automaticamente e
preenche os campos de distância — que continuam editáveis manualmente
se você preferir digitar os números direto.

### Coleta: preço fixo por rota + veículo, ou faixa por km

Por padrão, a coleta usa a tabela **"Faixas de Coleta por km"** (taxa
fixa + tarifa/km, igual já existia). Mas se a rota **filial de origem
(de onde o veículo sai) → cidade do cliente (onde ele coleta)**, para
o **veículo** escolhido no orçamento, estiver cadastrada em **"Coleta
com Preço Fixo por Cidade"** (na Tabela de Preços), esse valor fixo é
usado no lugar da faixa por km — útil para rotas onde a coleta tem um
preço acordado, diferente do cálculo por distância. A filial de
origem é sempre a filial mais próxima do cliente (a mesma que o botão
"Calcular distância" resolve automaticamente), e o veículo é o mesmo
escolhido pelo cálculo do frete principal (pelo peso/cubagem da carga)
— então o preço fixo só entra quando bater a combinação exata de
filial, cidade e veículo.

Uma linha de "Coleta com Preço Fixo por Cidade" pode cobrir **mais de
uma cidade** ao mesmo tempo: no campo de cidade, separe os nomes por
vírgula (ex: `Osasco, Barueri, Cotia`) — todas usam o mesmo valor fixo,
sem precisar de uma linha por cidade. Cada cidade só pode aparecer numa
linha por filial+veículo (cadastrar a mesma cidade em duas linhas
diferentes dá erro de conflito, pra não ficar ambíguo qual preço vale).

## Endpoints

### `GET /`
Interface web.

### `POST /orcamento`
Calcula o frete. O veículo é escolhido automaticamente pelo peso e pelo
volume dos paletes informados (não é mais um campo de entrada). Corpo
da requisição:

```json
{
  "peso": 8,
  "paletes": [
    {"comprimento": 40, "largura": 30, "altura": 25}
  ],
  "distancia": 350,
  "distancia_coleta": 0,
  "cidade_coleta": "",
  "cidade_origem": "",
  "cidade_destino": "",
  "valor_mercadoria": 1200,
  "categoria": "Geral",
  "transporte": "Rodoviário",
  "sla": "Padrão",
  "coleta_terceirizada": false,
  "transportadora_coleta_nome": "",
  "valor_coleta_terceirizada": 0,
  "entrega_terceirizada": false,
  "transportadora_entrega_nome": "",
  "valor_entrega_terceirizada": 0,
  "pedagio": 0,
  "distancia_retorno": 0
}
```

- `paletes`: lista de volumes (comprimento/largura/altura em cm) — o
  peso cubado é somado a partir do volume total e comparado com o peso
  real para decidir o veículo (`peso_considerado = max(peso, peso_cubado)`),
  junto com a capacidade em m³ de cada veículo.
- `distancia_coleta` e `cidade_coleta` são opcionais (só usados quando há
  retirada no cliente com frota própria — `cidade_coleta` é o endereço
  resolvido pela busca de distância, usado para checar se a rota tem
  preço fixo de coleta). `tarifa_km_manutencao` também incide sobre
  `distancia_coleta`, desde que a coleta não seja terceirizada.
- `cidade_origem` e `cidade_destino` são usadas para checar **taxas
  regionais** (ex: taxa de zona franca em Manaus) cadastradas em
  `/admin/taxas-regionais` — entram no cálculo se baterem com a cidade
  de origem ou de destino do frete — e **taxa de balsa** cadastrada em
  `/admin/taxas-balsa`, que exige a combinação exata cidade_origem →
  cidade_destino + veículo (ver [Cálculo do frete por
  veículo](#cálculo-do-frete-por-veículo)).
- `coleta_terceirizada`/`entrega_terceirizada`: quando a coleta ou a
  entrega final é feita por uma transportadora contratada (ver
  `/admin/transportadoras-terceirizadas`) em vez da frota própria — o
  valor combinado (`valor_coleta_terceirizada`/`valor_entrega_terceirizada`)
  substitui o cálculo por faixa/km desse trecho.
- `pedagio`: valor do pedágio da rota (preenchido automaticamente por
  `/geo/distancia` — catálogo de praças cadastrado quando existir um
  corredor pra rota, senão a estimativa do Google Maps quando
  `GOOGLE_MAPS_API_KEY` está configurada — ver seção "Pedágio: catálogo
  de praças por número de eixos"; sempre editável na tela).
- `distancia_retorno`: distância (km) do retorno vazio do veículo, do
  destino até a filial mais próxima — só quando a entrega é feita direto
  ao cliente pela frota própria. Cobrada pela `tarifa_km_retorno` do
  veículo; `tarifa_km_manutencao` também passa a incidir sobre ela (soma
  com a distância de ida — o desgaste do veículo acontece nos dois
  trechos).

### `POST /geo/distancia`
Calcula a distância rodoviária entre dois endereços (usado internamente
para o trecho principal do frete).
```json
{"origem": "Av. Paulista, 1000, São Paulo, SP", "destino": "Rua XV de Novembro, 500, Curitiba, PR"}
```

### `POST /geo/resolver-retirada`
Dado um endereço de retirada, retorna a filial mais próxima e a
distância de coleta até ela.
```json
{"endereco_retirada": "Rua Augusta, 500, São Paulo, SP"}
```
Resposta:
```json
{
  "filial_mais_proxima": "São Paulo",
  "filial_endereco": "Av. Exemplo, 100, São Paulo, SP",
  "distancia_coleta_km": 5.2,
  "duracao_coleta_min": 14,
  "endereco_resolvido": "Rua Augusta, 500, São Paulo, SP, Brasil"
}
```

### `POST /geo/resolver-entrega`
Mesma lógica de `/geo/resolver-retirada`, mas para o endereço de
**entrega**: usada quando a entrega final é terceirizada — a rota
principal (frota própria) vai só até a filial mais próxima achada aqui,
e o trecho filial → cliente fica por conta da transportadora contratada.
```json
{"endereco_entrega": "Rua Augusta, 500, São Paulo, SP"}
```

### `POST /geo/resolver-retorno`
Dado o endereço final da entrega, encontra a filial cadastrada mais
próxima para onde o veículo (vazio) volta depois de entregar — usado
para estimar `distancia_retorno` no orçamento (cobrada pela
`tarifa_km_retorno` do veículo).
```json
{"endereco_destino": "Rua Augusta, 500, São Paulo, SP"}
```

### `GET /parametros/{categorias|transportes|slas|filiais|veiculos|taxas-adicionais|faixas-coleta|transportadoras-terceirizadas|pracas-pedagio}`
Listam os valores atuais de cada tabela — úteis para montar campos de
seleção em qualquer sistema que consuma essa API.

### `GET|POST|PUT|DELETE /admin/pracas-pedagio` e `/admin/pedagios-rota`
CRUD do catálogo de praças de pedágio e dos corredores que as ligam —
ver "Pedágio: catálogo de praças por número de eixos". Exigem login de
administrador, igual aos outros endpoints `/admin/*`.

### `POST /admin/pracas-pedagio/importar-csv`
Importa/atualiza em lote o catálogo de praças a partir de um CSV (texto
já lido no navegador, não multipart) — `{"conteudo": "nome,rodovia,..."}`.
Faz upsert por nome+rodovia; devolve `{"criadas", "atualizadas", "erros"}`.

### `GET|POST|PUT|DELETE /admin/distancias-fixas`
CRUD de distâncias fixas por corredor — ver "Distância Fixa por
Corredor" acima. Exige login de administrador.

### `POST /admin/reload`
Recarrega os parâmetros direto do banco `frete.db`, sem reiniciar o
servidor. Use depois de editar dados no DB Browser.

### `GET /health`
Checagem simples de que a API está no ar.

### Autenticação

- `POST /auth/login` — `{"username": "...", "senha": "..."}`, devolve os
  dados do usuário e grava um cookie de sessão (httponly, válido por 12h).
- `POST /auth/logout` — encerra a sessão atual.
- `GET /auth/me` — dados do usuário logado (401 se não houver sessão).
- `POST /auth/trocar-senha` — `{"senha_atual": "...", "senha_nova": "..."}`,
  troca a senha do próprio usuário logado.

### `GET|POST|PUT|DELETE /admin/usuarios`
CRUD de usuários (só administrador) — mesmo padrão dos outros recursos
`/admin/*`: `GET` lista, `POST` cria, `PUT /admin/usuarios/{id}` edita
(a senha só é trocada se o campo `senha` vier preenchido) e
`DELETE /admin/usuarios/{id}` exclui. Sempre precisa sobrar pelo menos
um administrador ativo — tentar remover, desativar ou rebaixar o
último retorna `422`. Senhas (criação, edição e troca de senha) exigem
no mínimo 8 caracteres.

### `GET /admin/banco-dados`, `POST /admin/banco-dados/testar`, `POST /admin/banco-dados/aplicar`
Configuração de qual banco de dados a API usa — ver "Banco de dados
configurável" abaixo. `GET` devolve a config ativa (nunca a senha).
`POST .../testar` tenta conectar sem aplicar nada. `POST .../aplicar`
cria o schema no banco novo, migra todos os dados do banco atual pra
ele e só então troca a config ativa (se qualquer etapa falhar, o banco
em uso continua sendo o de antes).

> Todas as rotas `/admin/*` (Tabela de Preços, `/admin/reload`,
> `/admin/usuarios` e `/admin/banco-dados`) exigem login como
> administrador. `/historico`
> exige login (qualquer papel) para listar/salvar/ver — mas só quem
> salvou o orçamento (a conta logada, não o texto livre do campo
> "Responsável") ou um administrador pode excluir um registro do
> histórico (`DELETE /historico/{id}`, `403` caso contrário) ou corrigir
> o pedágio de um orçamento já salvo (`PUT /historico/{id}/pedagio`,
> mesma regra de dono/admin — recalcula o `frete_total` só pela diferença
> entre o pedágio antigo e o novo, sem reprocessar o resto do orçamento).
> `/orcamento`, `/geo/*` e `/parametros/*` continuam públicos — gerar um
> orçamento não exige login.
>
> O login tem limite de tentativas falhas (bloqueio temporário) tanto por
> IP quanto por usuário — protege contra força bruta mesmo quando várias
> pessoas dividem o mesmo IP (rede corporativa) ou quando o ataque tenta
> vários usuários a partir de IPs diferentes.

## Banco de dados configurável (SQLite / SQL Server / MySQL / PostgreSQL)

Por padrão o sistema usa SQLite (arquivo `frete.db` local, como sempre
funcionou — nenhuma configuração extra necessária). Pela tela
Configurações → "Banco de dados", um administrador pode trocar pra um
servidor SQL Server, MySQL ou PostgreSQL:

1. Escolha o tipo e preencha host/porta/banco/usuário/senha.
2. Clique em **"Testar conexão"** — confirma que dá pra conectar sem
   mudar nada ainda.
3. Clique em **"Migrar dados e aplicar"** — cria o schema no banco
   novo, copia **todos** os dados já cadastrados (filiais, veículos,
   taxas, histórico de orçamentos etc.) pra ele, e só então a API passa
   a usar esse banco novo — sem precisar reiniciar o processo. Se
   qualquer etapa falhar, o banco em uso continua sendo o anterior.

**Pré-requisitos:**
- SQL Server exige o **ODBC Driver 17 ou 18 for SQL Server** instalado
  no sistema operacional (não é um pacote Python — [baixe aqui](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server)).
  MySQL e PostgreSQL não exigem nada além do `pip install -r requirements.txt`.
- A config ativa (incluindo host/usuário/senha, se houver) fica em
  `db_config.json` na raiz do projeto — arquivo local, fora do git. A
  senha é gravada **cifrada** (Fernet/AES, chave local gerada na
  primeira vez em `db_config.key`, também fora do git); host/usuário
  ficam em texto claro, mesmo padrão de qualquer arquivo de config local.
  Sem `db_config.json`, o padrão é SQLite normalmente. Perder o arquivo
  `db_config.key` torna a senha já salva ilegível — basta recadastrar
  pela tela Configurações → "Banco de dados".

**Limitação conhecida:** o ambiente onde este recurso foi construído
não tinha SQL Server/MySQL/PostgreSQL disponíveis pra testar contra um
servidor de verdade — a sintaxe de cada dialeto foi escrita com base no
padrão documentado de cada um, mas só é confirmada de fato na tela
"Testar conexão". Se der erro de sintaxe/driver na primeira vez que
usar com um desses bancos, é esperado precisar de um ajuste fino.

## Sobre os serviços de mapa (Nominatim + OSRM, ou Google Maps)

Por padrão o cálculo de distância usa serviços públicos e gratuitos do
OpenStreetMap, sem necessidade de chave de API:
- **Nominatim** — converte endereço em coordenadas (geocodificação)
- **OSRM** — calcula a distância de rota rodoviária entre coordenadas

Esses serviços têm limite de uso educado (poucas requisições por
segundo), o que é suficiente para o volume de uma pessoa gerando
orçamentos internamente.

Se o volume crescer ou for preciso estimar pedágio, defina a variável
de ambiente `GOOGLE_MAPS_API_KEY` — a API muda automaticamente para a
Geocoding API + Routes API do Google Maps (mais tolerante a endereços
incompletos e traz estimativa de pedágio, usada para preencher o campo
`pedagio` do orçamento). `GET /api/status` mostra qual provedor está
ativo no momento (`"geo_provider": "google"` ou `"osm"`).

### Variáveis de ambiente

| Variável | Padrão | Efeito |
|---|---|---|
| `GOOGLE_MAPS_API_KEY` | (vazio) | Se definida, usa Google Maps (Geocoding + Routes) em vez de Nominatim/OSRM. |
| `GEO_COUNTRY_CODES` | `br` | Restringe a busca de endereço a este(s) país(es) (Nominatim: `countrycodes`; Google: `region`/`components`). |
| `GEO_USER_AGENT` | `SistemaOrcamentoFrete/1.0 (uso interno da empresa)` | User-Agent enviado ao Nominatim (exigido pela política de uso deles). |
| `FRETE_DB_PATH` | `frete.db` na pasta do projeto | Caminho do arquivo do banco SQLite — útil para apontar para outro arquivo/pasta. |
| `CORS_ORIGINS` | `http://localhost:8000,http://127.0.0.1:8000` | Lista de origens (separadas por vírgula) autorizadas a chamar a API via CORS. Só importa se algo fora da própria UI (servida pelo FastAPI) consumir a API do navegador noutro host/porta. |
| `TRUSTED_PROXY_HOSTS` | (vazio) | Lista de IPs (separados por vírgula) de proxy(s) reverso(s) confiáveis — quando definida, a API passa a confiar nos headers `X-Forwarded-Proto`/`X-Forwarded-For` enviados por eles. Necessário no deploy com proxy reverso fazendo TLS (ver seção acima): sem isso, atrás do proxy o cookie de sessão sai sem `secure` e o rate limit de login/geo vira um limite único compartilhado por todo mundo (a API só enxerga o IP do proxy). Normalmente `127.0.0.1`, quando o proxy roda na mesma máquina. **Nunca** aponte para um IP que não seja realmente o do seu proxy — confiar no header errado permite forjar IP/scheme. |

## Estrutura dos arquivos

```
frete_project/
├── main.py                    # Monta o app FastAPI: CORS, lifespan, estáticos, inclui os routers
├── schemas.py                 # Modelos Pydantic (corpo de requisição) de todas as rotas
├── deps.py                    # Dependências de autenticação e helpers de CRUD admin
├── routers/                   # Uma rota por domínio (inclusos em main.py)
│   ├── auth.py                 # /auth/*
│   ├── geo.py                  # /geo/*
│   ├── orcamento.py             # /orcamento
│   ├── historico.py            # /historico/*
│   ├── parametros.py           # /parametros/* (leitura pública)
│   ├── admin_precos.py         # /admin/* (Tabela de Preços) + /admin/reload
│   └── admin_usuarios.py       # /admin/usuarios (CRUD de usuários)
├── frete_service.py           # Leitura do banco + lógica de cálculo do frete
├── geo_service.py             # Geocodificação, distância e filial mais próxima
├── auth_service.py            # Login, sessão e hash de senha
├── export_service.py          # Exportação de orçamento do histórico para planilha
├── frete_db.py                # Schema do banco SQLite e dados de exemplo
├── frete.db                   # Banco de dados (criado automaticamente)
├── index.html                 # Interface web (HTML) — CSS e JS ficam em assets/
├── tests/                     # Testes (pytest) — cálculo de frete, auth, API, exportação
├── requirements.txt
├── requirements-dev.txt
├── README.md
├── iniciar_api.bat
└── assets/
    ├── app.js                  # JS da interface (index.html)
    ├── style.css                # CSS da interface (index.html)
    ├── favicon-16x16.png
    ├── favicon-32x32.png
    └── supersonic-logo-dark.png
```