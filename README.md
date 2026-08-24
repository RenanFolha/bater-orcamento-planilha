# Sistema de Orçamento de Frete

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
| `coleta_cidades_fixas`   | Preço fixo de coleta por rota (filial de origem → cidade do cliente) + veículo (sobrepõe a faixa por km)|
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

- `/admin/veiculos`
- `/admin/taxas-adicionais`
- `/admin/coleta-cidades-fixas`
- `/admin/faixas-coleta`
- `/admin/categorias`
- `/admin/transportes`
- `/admin/slas`

Nomes duplicados (categoria, transporte ou SLA repetido) retornam
`409 Conflict` com uma mensagem explicando o problema.

## Cálculo do frete por veículo

O frete principal é calculado com base no **veículo** escolhido nas
abas do topo da tela (Carreta, Truck/Toco, VUC, Van/HR, Caminhonete —
edite/adicione veículos na Tabela de Preços). Cada veículo tem:

- **Tarifa por km** (R$/km × distância percorrida)
- **Peso incluso** (kg que já vêm cobertos pela tarifa)
- **Valor por kg excedente** (cobrado sobre o que passar do peso incluso)

```
frete_base = (tarifa_km × distância) + (peso_excedente × valor_kg_excedente)
frete_ajustado = frete_base × multiplicador_categoria × multiplicador_transporte × multiplicador_sla
```

Em cima disso somam-se:
- **Taxas Adicionais** — lista editável (GRIS, Ad Valorem, Pedágio, Taxa
  de Localidade etc.), cada uma fixa em R$ ou % do valor da mercadoria.
- **Taxa de coleta** — só quando há retirada no cliente (veja abaixo).

```
frete_total = frete_ajustado + coleta + taxas_adicionais
```

> As tabelas antigas de "tipo de frete" (`faixas_peso`/`faixas_distancia`)
> continuam existindo no banco por compatibilidade, mas não são mais
> usadas no cálculo — o veículo assumiu esse papel.

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

## Endpoints

### `GET /`
Interface web.

### `POST /orcamento`
Calcula o frete. Corpo da requisição:

```json
{
  "peso": 8,
  "comprimento": 40,
  "largura": 30,
  "altura": 25,
  "distancia": 350,
  "distancia_coleta": 0,
  "cidade_coleta": "",
  "valor_mercadoria": 1200,
  "veiculo": "VUC",
  "categoria": "Geral",
  "transporte": "Rodoviário",
  "sla": "Padrão"
}
```

`distancia_coleta` e `cidade_coleta` são opcionais (só usados quando há
retirada no cliente — `cidade_coleta` é o endereço resolvido pela busca
de distância, usado para checar se a cidade tem preço fixo de coleta).

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

### `GET /parametros/{categorias|transportes|slas|filiais|veiculos|taxas-adicionais|faixas-coleta|geral}`
Listam os valores atuais de cada tabela — úteis para montar campos de
seleção em qualquer sistema que consuma essa API.

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
último retorna `422`.

> Todas as rotas `/admin/*` (Tabela de Preços, `/admin/reload` e
> `/admin/usuarios`) exigem login como administrador. `/historico`
> exige login (qualquer papel). `/orcamento`, `/geo/*` e `/parametros/*`
> continuam públicos — gerar um orçamento não exige login.

## Sobre os serviços de mapa (Nominatim + OSRM)

O cálculo de distância usa serviços públicos e gratuitos do
OpenStreetMap, sem necessidade de chave de API:
- **Nominatim** — converte endereço em coordenadas (geocodificação)
- **OSRM** — calcula a distância de rota rodoviária entre coordenadas

Esses serviços têm limite de uso educado (poucas requisições por
segundo), o que é suficiente para o volume de uma pessoa gerando
orçamentos internamente. Se o volume crescer muito, considere hospedar
sua própria instância ou migrar para um provedor pago (Google Maps,
Mapbox etc.) — nesse caso, é só trocar a implementação em
`geo_service.py`.

## Estrutura dos arquivos

```
frete_project/
├── main.py                    # Rotas da API (FastAPI)
├── frete_service.py           # Leitura do banco + lógica de cálculo do frete
├── geo_service.py             # Geocodificação, distância e filial mais próxima
├── auth_service.py            # Login, sessão e hash de senha
├── frete_db.py                # Schema do banco SQLite e dados de exemplo
├── frete.db                   # Banco de dados (criado automaticamente)
├── index.html                 # Interface web
├── requirements.txt
├── README.md
├── iniciar_api.bat
└── assets/
    ├── favicon-16x16.png
    ├── favicon-32x32.png
    ├── supersonic-wordmark.png
    └── supersonic-logo-dark.png
```