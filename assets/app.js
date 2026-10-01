const API_BASE = ""; // mesma origem (servido pelo próprio FastAPI)

// Usado no seletor de UF de origem das Escalas Obrigatórias (ver
// carregarTabelaPrecos) -- mesmas siglas que frete_service.py reconhece.
const UFS_BRASIL = [
  'AC', 'AL', 'AP', 'AM', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MT', 'MS',
  'MG', 'PA', 'PB', 'PR', 'PE', 'PI', 'RJ', 'RN', 'RS', 'RO', 'RR', 'SC',
  'SP', 'SE', 'TO',
];

const fmtBRL = (v) => new Intl.NumberFormat('pt-BR', {style:'currency', currency:'BRL', minimumFractionDigits:2, maximumFractionDigits:2}).format(v);
const fmtMult = (v) => v.toFixed(2).replace('.', ',') + 'x';

// Escapa texto vindo de dados salvos pelo usuário (ex: cliente/responsável
// do histórico) antes de inserir em innerHTML — sem isso, um valor como
// "<img src=x onerror=...>" salvo no histórico executaria no navegador de
// quem visualizasse a lista.
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[c]));

// Lista TODOS os campos que calcular_orcamento devolve (entrada +
// calculos_intermediarios + resultado), na ordem em que a conta é feita —
// usada por renderizarMemoriaCalculo pra mostrar cada variável usada na
// cotação, não só as que já tinham linha própria no resumo curado acima.
// Um campo novo que o backend passe a devolver não aparece aqui sozinho
// (precisa adicionar a linha), mas nada do que já existe fica escondido.
const MEMORIA_CALCULO_CAMPOS = [
  {header: 'Entrada'},
  {chave: 'peso_kg', rotulo: 'Peso informado', tipo: 'kg'},
  {chave: 'distancia_km', rotulo: 'Distância do frete', tipo: 'km'},
  {chave: 'rota_obrigatoria', rotulo: 'Rota obrigatória (via filial)', tipo: 'texto'},
  {chave: 'distancia_coleta_km', rotulo: 'Distância de coleta', tipo: 'km'},
  {chave: 'valor_mercadoria', rotulo: 'Valor da mercadoria', tipo: 'brl'},
  {chave: 'veiculo', rotulo: 'Veículo escolhido', tipo: 'texto'},
  {chave: 'categoria', rotulo: 'Categoria', tipo: 'texto'},
  {chave: 'transporte', rotulo: 'Transporte', tipo: 'texto'},
  {chave: 'sla', rotulo: 'SLA', tipo: 'texto'},

  {header: 'Escolha do veículo (peso × volume)'},
  {chave: 'fator_cubagem', rotulo: 'Fator de cubagem do transporte', tipo: 'num'},
  {chave: 'peso_cubado_kg', rotulo: 'Peso cubado', tipo: 'kg'},
  {chave: 'peso_considerado_kg', rotulo: 'Peso considerado (maior entre real e cubado)', tipo: 'kg'},
  {chave: 'volume_total_m3', rotulo: 'Volume total da carga', tipo: 'm3'},
  {chave: 'capacidade_util_m3_veiculo', rotulo: 'Capacidade útil do veículo', tipo: 'm3'},
  {chave: 'percentual_capacidade_util_veiculo', rotulo: '% da capacidade que pode ocupar', tipo: 'pct'},
  {chave: 'capacidade_disponivel_m3_veiculo', rotulo: 'Capacidade disponível (útil × %)', tipo: 'm3'},
  {chave: 'capacidade_ocupada_pct', rotulo: 'Ocupação do veículo', tipo: 'pct'},

  {header: 'Frete base'},
  {chave: 'tarifa_km_veiculo', rotulo: 'Tarifa por km do veículo', tipo: 'brl'},
  {chave: 'faixa_km_aplicada', rotulo: 'Veio de faixa por km (não da tarifa fixa)?', tipo: 'bool'},
  {chave: 'custo_km', rotulo: 'Custo por km × distância', tipo: 'brl'},
  {chave: 'peso_excedente_kg', rotulo: 'Peso excedente (acima do "até" do veículo)', tipo: 'kg'},
  {chave: 'valor_tonelada_excedente', rotulo: 'Valor por tonelada excedente', tipo: 'brl'},
  {chave: 'custo_peso_excedente', rotulo: 'Custo do peso excedente', tipo: 'brl'},
  // Só presentes em orçamentos Fracionado (ver
  // frete_service.calcular_orcamento_fracionado) -- a linha some por
  // completo nos orçamentos de Carreta Fechada, que não têm esses campos
  // (ver renderizarMemoriaCalculo).
  {chave: 'faixa_peso_de', rotulo: '[Fracionado] Faixa de peso — de (kg)', tipo: 'kg'},
  {chave: 'faixa_peso_ate', rotulo: '[Fracionado] Faixa de peso — até (kg)', tipo: 'kg'},
  {chave: 'tarifa_base_peso', rotulo: '[Fracionado] Tarifa base da faixa de peso', tipo: 'brl'},
  {chave: 'custo_kg_adicional_peso', rotulo: '[Fracionado] Custo/kg adicional da faixa de peso', tipo: 'brl'},
  {chave: 'custo_base_peso', rotulo: '[Fracionado] Custo base (peso)', tipo: 'brl'},
  {chave: 'faixa_distancia_de', rotulo: '[Fracionado] Faixa de distância — de (km)', tipo: 'km'},
  {chave: 'faixa_distancia_ate', rotulo: '[Fracionado] Faixa de distância — até (km)', tipo: 'km'},
  {chave: 'taxa_fixa_distancia', rotulo: '[Fracionado] Taxa fixa da faixa de distância', tipo: 'brl'},
  {chave: 'tarifa_km_distancia', rotulo: '[Fracionado] Tarifa/km da faixa de distância', tipo: 'brl'},
  {chave: 'custo_base_distancia', rotulo: '[Fracionado] Custo base (distância)', tipo: 'brl'},
  {chave: 'frete_base', rotulo: 'Frete base', tipo: 'brl'},
  {chave: 'frete_ajustado', rotulo: 'Frete ajustado', tipo: 'brl'},

  {header: 'Coleta e entrega'},
  {chave: 'coleta_terceirizada', rotulo: 'Coleta terceirizada?', tipo: 'bool'},
  {chave: 'transportadora_coleta_nome', rotulo: 'Transportadora da coleta', tipo: 'texto'},
  {chave: 'coleta_fixa_por_cidade', rotulo: 'Coleta com preço fixo por cidade?', tipo: 'bool'},
  {chave: 'coleta_fixa_outro_veiculo', rotulo: 'Preço fixo cadastrado só p/ outro veículo', tipo: 'lista_veiculos'},
  {chave: 'custo_coleta', rotulo: 'Custo de coleta', tipo: 'brl'},
  {chave: 'entrega_terceirizada', rotulo: 'Entrega terceirizada?', tipo: 'bool'},
  {chave: 'transportadora_entrega_nome', rotulo: 'Transportadora da entrega', tipo: 'texto'},
  {chave: 'custo_entrega_terceirizada', rotulo: 'Custo de entrega terceirizada', tipo: 'brl'},

  {header: 'Pedágio, manutenção e retorno vazio'},
  {chave: 'pedagio', rotulo: 'Pedágio', tipo: 'brl'},
  {chave: 'pedagio_estimado_pct', rotulo: 'Pedágio estimado (sem praça cadastrada)', tipo: 'pct'},
  {chave: 'pedagio_pracas', rotulo: 'Praças de pedágio aplicadas', tipo: 'lista_veiculos'},
  {chave: 'tarifa_km_manutencao', rotulo: 'Tarifa de manutenção por km', tipo: 'brl'},
  {chave: 'distancia_manutencao_km', rotulo: 'Distância considerada na manutenção (ida + coleta própria + retorno)', tipo: 'km'},
  {chave: 'custo_manutencao', rotulo: 'Custo de manutenção', tipo: 'brl'},
  {chave: 'tarifa_km_retorno', rotulo: 'Tarifa de retorno vazio por km', tipo: 'brl'},
  {chave: 'distancia_retorno_km', rotulo: 'Distância de retorno vazio', tipo: 'km'},
  {chave: 'custo_retorno', rotulo: 'Custo de retorno vazio', tipo: 'brl'},

  {header: 'Custo da operação'},
  {chave: 'custos_extras', rotulo: 'Custos extras aplicados', tipo: 'lista_custo_extra'},
  {chave: 'custo_extra_total', rotulo: 'Total de custos extras', tipo: 'brl'},
  {chave: 'taxa_balsa', rotulo: 'Taxa de balsa aplicada (ida)', tipo: 'balsa'},
  {chave: 'taxa_balsa_retorno', rotulo: 'Taxa de balsa aplicada (retorno)', tipo: 'balsa'},
  {chave: 'balsa_outro_veiculo', rotulo: 'Taxa de balsa cadastrada só p/ outro veículo', tipo: 'lista_veiculos'},
  {chave: 'custo_balsa', rotulo: 'Custo de balsa (ida + retorno)', tipo: 'brl'},
  {chave: 'diaria_veiculo', rotulo: 'Diária de carreta/cavalo aplicada', tipo: 'diaria_veiculo'},
  {chave: 'custo_diaria_veiculo', rotulo: 'Custo de diária de carreta e cavalo', tipo: 'brl'},
  {chave: 'total_custo_operacao', rotulo: 'Total do custo da operação', tipo: 'brl'},

  {header: 'Taxas'},
  {chave: 'taxas_adicionais', rotulo: 'Taxas adicionais aplicadas', tipo: 'lista_taxa'},
  {chave: 'custo_taxas_adicionais', rotulo: 'Total de taxas adicionais', tipo: 'brl'},
  {chave: 'taxas_regionais', rotulo: 'Taxa fluvial (RCA) aplicada', tipo: 'lista_taxa_regional'},
  {chave: 'custo_taxas_regionais', rotulo: 'Total de taxa fluvial (RCA)', tipo: 'brl'},
  {chave: 'total_impostos_taxas', rotulo: 'Total de impostos e taxas', tipo: 'brl'},

  {header: 'PIS/COFINS'},
  {chave: 'aliquota_pis_cofins_pct', rotulo: 'Alíquota de PIS/COFINS', tipo: 'pct'},
  {chave: 'frete_sem_pis_cofins', rotulo: 'Frete sem PIS/COFINS', tipo: 'brl'},
  {chave: 'valor_pis_cofins', rotulo: 'Valor do PIS/COFINS (gross-up)', tipo: 'brl'},

  {header: 'Margem de lucro'},
  {chave: 'margem_lucro_pct', rotulo: 'Margem de lucro', tipo: 'pct'},
  {
    chave: 'markup_lucro', rotulo: 'Markup aplicado', tipo: 'mult',
    // Não vem pronto do backend (só margem_lucro_pct, em %) -- markup é
    // essa mesma margem expressa como multiplicador (40% = 1,40x), igual
    // ao formato já usado pra multiplicador_categoria/transporte/sla.
    calculado: (fonte) => 1 + (fonte.margem_lucro_pct ?? 0) / 100,
  },
  {chave: 'frete_sem_margem_lucro', rotulo: 'Frete sem margem de lucro (já com PIS/COFINS)', tipo: 'brl'},
  {chave: 'valor_margem_lucro', rotulo: 'Valor da margem de lucro', tipo: 'brl'},

  {header: 'ICMS'},
  {chave: 'uf_origem_icms', rotulo: 'UF de origem', tipo: 'texto'},
  {chave: 'uf_destino_icms', rotulo: 'UF de destino', tipo: 'texto'},
  {chave: 'aliquota_icms_pct', rotulo: 'Alíquota de ICMS', tipo: 'pct'},
  {chave: 'frete_sem_icms', rotulo: 'Frete sem ICMS (já com margem de lucro)', tipo: 'brl'},
  {chave: 'valor_icms', rotulo: 'Valor do ICMS (% simples somado por fora, não gross-up)', tipo: 'brl'},
  {chave: 'ajuste_piso_markup', rotulo: 'Ajuste pro markup mínimo de 1,4x', tipo: 'brl'},

  {header: 'Resultado'},
  {chave: 'frete_total', rotulo: 'Frete total', tipo: 'brl'},
  {chave: 'prazo_estimado_dias_uteis', rotulo: 'Prazo estimado', tipo: 'dias'},
];

function _formatarValorMemoria(v, tipo){
  if(v === null || v === undefined || v === '') return '—';
  switch(tipo){
    case 'brl': return fmtBRL(v);
    case 'pct': return `${v}%`;
    case 'mult': return fmtMult(v);
    case 'kg': return `${v} kg`;
    case 'm3': return `${v} m³`;
    case 'km': return `${v} km`;
    case 'dias': return `${v} dias úteis`;
    case 'bool': return v ? 'Sim' : 'Não';
    case 'lista_taxa':
      return (v && v.length)
        ? v.map(t => `${t.nome} (${t.tipo === 'percentual' ? t.valor_configurado + '%' : fmtBRL(t.valor_configurado)}) = ${fmtBRL(t.valor_aplicado)}`).join('; ')
        : 'nenhuma';
    case 'lista_taxa_regional':
      return (v && v.length)
        ? v.map(t => `${t.nome} — ${t.cidade} (${t.tipo === 'percentual' ? t.valor_configurado + '%' : fmtBRL(t.valor_configurado)}) = ${fmtBRL(t.valor_aplicado)}`).join('; ')
        : 'nenhuma';
    case 'balsa':
      return v
        ? `${v.cidade_origem} → ${v.cidade_destino} (${v.veiculo}, ${v.tipo === 'percentual' ? v.valor_configurado + '%' : fmtBRL(v.valor_configurado)}) = ${fmtBRL(v.valor_aplicado)}`
        : 'não aplicada';
    case 'diaria_veiculo':
      return v
        ? `${v.uf}: carreta ${fmtBRL(v.valor_carreta)} + cavalo ${fmtBRL(v.valor_cavalo)}`
        : 'não aplicada';
    case 'lista_veiculos':
      return (v && v.length) ? v.join(', ') : '—';
    case 'lista_custo_extra':
      return (v && v.length)
        ? v.map(c => `${c.categoria} = ${fmtBRL(c.valor_aplicado)}`).join('; ')
        : 'nenhum';
    default: return String(v);
  }
}

// Renderiza a lista completa de variáveis usadas na cotação. `data` é o
// objeto {entrada, calculos_intermediarios, resultado} devolvido por
// POST /orcamento (mesmo formato salvo em dados.resultado no histórico).
function renderizarMemoriaCalculo(data, containerId = 'bloco-memoria-calculo', comTitulo = true){
  const container = document.getElementById(containerId);
  if(!container || !data) return;
  const fonte = {...data.entrada, ...data.calculos_intermediarios, ...data.resultado};
  const linhas = MEMORIA_CALCULO_CAMPOS.map(item => {
    if(item.header){
      return `<div style="margin:12px 0 4px;font-size:10.5px;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-dim);">${esc(item.header)}</div>`;
    }
    // Campos exclusivos de um tipo de orçamento (ex: "[Fracionado] ..." só
    // existe no resultado de calcular_orcamento_fracionado, custo_km só no
    // de calcular_orcamento) nem entram como chave no outro tipo -- pula a
    // linha inteira em vez de mostrar "—", pra não poluir a memória de
    // cálculo com campos que não fazem sentido pro orçamento em questão.
    if(!item.calculado && fonte[item.chave] === undefined) return '';
    const bruto = item.calculado ? item.calculado(fonte) : fonte[item.chave];
    const valor = _formatarValorMemoria(bruto, item.tipo);
    return `<div class="line"><span>${esc(item.rotulo)}</span><span>${esc(valor)}</span></div>`;
  }).join('');
  container.innerHTML = (comTitulo ? '<h3>Memória de cálculo completa</h3>' : '') + linhas;
}

// Máscara de campo monetário: trata o que foi digitado como centavos
// (só dígitos) e formata com separador de milhar "." e decimal ",",
// igual ao padrão de moeda brasileiro.
function formatarValorMoeda(v){
  return (Number(v) || 0).toLocaleString('pt-BR', {minimumFractionDigits: 2, maximumFractionDigits: 2});
}
function formatarMoedaDigitando(el){
  let digitos = el.value.replace(/\D/g, '');
  if(digitos === '') digitos = '0';
  el.value = formatarValorMoeda(parseInt(digitos, 10) / 100);
}
function valorMoedaParaNumero(str){
  if(str == null || str === '') return 0;
  const limpo = String(str).replace(/\./g, '').replace(',', '.');
  const n = parseFloat(limpo);
  return isNaN(n) ? 0 : n;
}

// Máscara de campo de peso: ao contrário da moeda, não trata os dígitos
// como casas decimais fixas — só formata a parte inteira com separador
// de milhar "." enquanto digita, preservando até 2 casas decimais depois
// da vírgula (ex: "1200" -> "1.200", "1200,5" -> "1.200,5").
function formatarPesoDigitando(el){
  let valor = el.value.replace(/[^\d,]/g, '');
  const [parteInteira, ...resto] = valor.split(',');
  const inteiroLimpo = parteInteira.replace(/^0+(?=\d)/, '') || '0';
  const inteiroFormatado = Number(inteiroLimpo).toLocaleString('pt-BR');
  const decimal = resto.length ? resto.join('').slice(0, 2) : null;
  el.value = decimal !== null ? `${inteiroFormatado},${decimal}` : inteiroFormatado;
}
// Mesmo parser de número pt-BR de valorMoedaParaNumero (troca . e , de
// lugar) — nome próprio só pra deixar claro o uso (peso, não R$) nos
// pontos que chamam.
const pesoParaNumero = valorMoedaParaNumero;

function preencherOpcoes(selectEl, data, labelKey='nome'){
  selectEl.replaceChildren();
  for(const item of data){
    const option = document.createElement('option');
    option.value = item[labelKey];
    option.textContent = item[labelKey];
    selectEl.appendChild(option);
  }
}

async function carregarOpcoes(endpoint, selectEl, labelKey='nome'){
  try{
    const res = await fetch(`${API_BASE}/parametros/${endpoint}`);
    if(!res.ok){
      throw new Error(`Erro HTTP ${res.status}`);
    }
    const data = await res.json();
    preencherOpcoes(selectEl, data, labelKey);
  }catch(e){
    selectEl.replaceChildren();
    const option = document.createElement('option');
    option.value = '';
    option.textContent = 'Erro ao carregar';
    selectEl.appendChild(option);
    throw e;
  }
}

const form = document.getElementById('form-frete');
const btn = document.getElementById('btn-calc');
const errorBox = document.getElementById('error-box');
const statusTag = document.getElementById('status-tag');
const resultEmpty = document.getElementById('result-empty');
const resultContent = document.getElementById('result-content');
let ultimoOrcamento = null;
const stamp = document.getElementById('stamp');
document.getElementById('config-conn-status').textContent = location.origin;

// GRIS/Ad Valorem cadastrados em Tabela de Preços (ver
// routers/parametros.py::listar_taxas_adicionais_publico) -- usados só
// pra pré-preencher os campos digitáveis 'gris_pct'/'ad_valorem_pct' (e
// os equivalentes 'frac-') com o valor cadastrado; digitar um valor MENOR
// que o cadastrado é rejeitado pela API (ver
// fs._piso_taxa_customizavel/calcular_orcamento). 0 quando não há nenhuma
// taxa cadastrada com esse nome.
let taxasCustomizaveisCache = {gris: 0, adValorem: 0};

async function carregarTaxasCustomizaveis(){
  try{
    const res = await fetch(`${API_BASE}/parametros/taxas-adicionais`);
    if(!res.ok) throw new Error(`Erro HTTP ${res.status}`);
    const data = await res.json();
    const gris = data.find(t => t.nome.trim().toLowerCase() === 'gris');
    const adValorem = data.find(t => t.nome.trim().toLowerCase() === 'ad valorem');
    taxasCustomizaveisCache = {gris: gris ? gris.valor : 0, adValorem: adValorem ? adValorem.valor : 0};
  }catch(e){
    taxasCustomizaveisCache = {gris: 0, adValorem: 0};
  }
}

function preencherCamposTaxasCustomizaveis(idGris, idAdValorem){
  const campoGris = document.getElementById(idGris);
  const campoAdValorem = document.getElementById(idAdValorem);
  // min = % cadastrado -- trava no navegador pra não deixar digitar um
  // valor abaixo do cadastrado (a API também rejeita, ver
  // fs._piso_taxa_customizavel/calcular_orcamento; isso aqui só evita a
  // viagem até o servidor pra descobrir).
  campoGris.min = taxasCustomizaveisCache.gris;
  campoGris.value = taxasCustomizaveisCache.gris;
  campoAdValorem.min = taxasCustomizaveisCache.adValorem;
  campoAdValorem.value = taxasCustomizaveisCache.adValorem;
}

// Lucro em cima do % cadastrado em Tabela de Preços: GRIS/Ad Valorem são
// digitáveis por orçamento (ver acima) -- qualquer % digitado ACIMA do
// cadastrado (o piso/custo real, ver fs._piso_taxa_customizavel) não é
// custo, é margem extra dessa cotação específica. Mostra isso ao vivo
// embaixo de cada campo, sempre que o % digitado ou o valor da
// mercadoria mudar (ambos entram na conta: lucro = valor_mercadoria *
// (% digitado - % cadastrado) / 100).
function atualizarLucroTaxaCustomizavel(idInput, idHint, idValorMercadoria, pisoCadastrado){
  const input = document.getElementById(idInput);
  const hint = document.getElementById(idHint);
  if(!input || !hint) return;
  const pctDigitado = parseFloat(input.value);
  const valorMercadoria = valorMoedaParaNumero(document.getElementById(idValorMercadoria).value);
  if(isNaN(pctDigitado) || valorMercadoria <= 0){
    hint.textContent = '';
    return;
  }
  const pisoFmt = pisoCadastrado.toLocaleString('pt-BR', {maximumFractionDigits: 4});
  const diferencaPct = pctDigitado - pisoCadastrado;
  if(diferencaPct <= 0.0001){
    hint.style.color = 'var(--text-dim)';
    hint.textContent = `Sem lucro extra — igual ao cadastrado (${pisoFmt}%).`;
  }else{
    const lucro = valorMercadoria * diferencaPct / 100;
    const diferencaFmt = diferencaPct.toLocaleString('pt-BR', {maximumFractionDigits: 4});
    hint.style.color = 'var(--ok)';
    hint.textContent = `Lucro acima da tabela: ${fmtBRL(lucro)} (+${diferencaFmt} pontos sobre o cadastrado, ${pisoFmt}%).`;
  }
}

function atualizarLucrosTaxasCustomizaveis(prefixo){
  atualizarLucroTaxaCustomizavel(
    `${prefixo}gris_pct`, `${prefixo}gris_pct-lucro`, `${prefixo}valor_mercadoria`, taxasCustomizaveisCache.gris,
  );
  atualizarLucroTaxaCustomizavel(
    `${prefixo}ad_valorem_pct`, `${prefixo}ad_valorem_pct-lucro`, `${prefixo}valor_mercadoria`, taxasCustomizaveisCache.adValorem,
  );
}

for(const prefixo of ['', 'frac-']){
  for(const campo of ['gris_pct', 'ad_valorem_pct', 'valor_mercadoria']){
    const el = document.getElementById(`${prefixo}${campo}`);
    if(el) el.addEventListener('input', () => atualizarLucrosTaxasCustomizaveis(prefixo));
  }
}

async function inicializarFormulario(){
  let carregouParametros = false;
  btn.disabled = true;
  btn.textContent = 'Carregando...';
  statusTag.textContent = 'Conectando';
  try{
    await Promise.all([
      carregarOpcoes('categorias', document.getElementById('categoria')),
      carregarTransportes(document.getElementById('transporte')),
      carregarOpcoes('slas', document.getElementById('sla')),
      carregarFiliais(),
      carregarTransportadoras(),
      carregarTaxasCustomizaveis(),
    ]);
    carregouParametros = true;
    statusTag.textContent = 'Aguardando';
    preencherCamposTaxasCustomizaveis('gris_pct', 'ad_valorem_pct');
    atualizarLucrosTaxasCustomizaveis('');
    // "Geral" é a categoria padrão (multiplicador 1.00, sem cuidado
    // especial) -- pré-seleciona pra cobrir o caso comum sem exigir que a
    // pessoa escolha toda vez.
    const categoriaSel = document.getElementById('categoria');
    if([...categoriaSel.options].some(o => o.value === 'Geral')){
      categoriaSel.value = 'Geral';
    }
    atualizarCubagem();
  }catch(err){
    errorBox.textContent = 'Não foi possível carregar os parâmetros. Verifique se a API está ativa.';
    errorBox.classList.add('show');
    statusTag.textContent = 'Erro';
  }finally{
    btn.disabled = !carregouParametros;
    btn.textContent = carregouParametros ? 'Calcular frete' : 'Parâmetros indisponíveis';
  }
}

let filiaisCache = [];
let transportadorasCache = [];
let transportesCache = [];

// Igual carregarOpcoes (mesmo fallback de erro no select), mas guarda a
// resposta inteira em transportesCache também -- usado por
// atualizarCubagem() pra achar o fator_cubagem do transporte escolhido,
// sem precisar de um segundo fetch no mesmo endpoint.
async function carregarTransportes(selectEl){
  try{
    const res = await fetch(`${API_BASE}/parametros/transportes`);
    if(!res.ok) throw new Error(`Erro HTTP ${res.status}`);
    transportesCache = await res.json();
    preencherOpcoes(selectEl, transportesCache);
  }catch(e){
    selectEl.replaceChildren();
    const option = document.createElement('option');
    option.value = '';
    option.textContent = 'Erro ao carregar';
    selectEl.appendChild(option);
    throw e;
  }
}

function coletarPaletes(){
  const comprimentos = document.querySelectorAll('.palete-comprimento');
  const larguras = document.querySelectorAll('.palete-largura');
  const alturas = document.querySelectorAll('.palete-altura');
  const quantidades = document.querySelectorAll('.palete-quantidade');
  return Array.from(comprimentos).map((el, i) => ({
    comprimento: parseFloat(el.value) || 0,
    largura: parseFloat(larguras[i].value) || 0,
    altura: parseFloat(alturas[i].value) || 0,
    quantidade: parseInt(quantidades[i].value, 10) || 1,
  }));
}

function criarLinhaPalete(){
  const wrap = document.getElementById('paletes-extra');
  const row = document.createElement('div');
  row.className = 'row2 row2-palete palete-row';
  row.innerHTML = `
    <div class="field">
      <div class="idx">+</div>
      <div>
        <label>Comprimento (cm)</label>
        <input type="number" class="palete-comprimento" min="0.1" step="0.01" value="40" required>
      </div>
    </div>
    <div class="field">
      <div class="idx">+</div>
      <div>
        <label>Largura (cm)</label>
        <input type="number" class="palete-largura" min="0.1" step="0.01" value="30" required>
      </div>
    </div>
    <div class="field">
      <div class="idx">+</div>
      <div>
        <label>Altura (cm)</label>
        <input type="number" class="palete-altura" min="0.1" step="0.01" value="25" required>
      </div>
    </div>
    <div class="field">
      <div class="idx">×</div>
      <div>
        <label>Qtde</label>
        <input type="number" class="palete-quantidade" min="1" step="1" value="1" title="Quantidade de paletes idênticos com essas mesmas dimensões" required>
      </div>
    </div>
    <button type="button" class="btn-icone excluir btn-remove-palete" title="Remover este palete">&times;</button>
  `;
  wrap.appendChild(row);
  row.querySelector('.btn-remove-palete').addEventListener('click', () => {
    row.remove();
    atualizarCubagem();
  });
  row.querySelectorAll('input').forEach(inp => inp.addEventListener('input', atualizarCubagem));
}

document.getElementById('btn-add-palete').addEventListener('click', criarLinhaPalete);

function atualizarCubagem(){
  const cubagemInfo = document.getElementById('cubagem-info');
  const peso = pesoParaNumero(document.getElementById('peso').value) || 0;
  const paletes = coletarPaletes().filter(p => p.comprimento > 0 && p.largura > 0 && p.altura > 0);
  const nomeTransporte = document.getElementById('transporte').value;
  const transp = transportesCache.find(t => t.nome === nomeTransporte);

  if(!transp || !transp.fator_cubagem || paletes.length === 0){
    cubagemInfo.textContent = '';
    return;
  }

  const volumeCm3Total = paletes.reduce((soma, p) => soma + (p.comprimento * p.largura * p.altura * p.quantidade), 0);
  const volumeM3Total = volumeCm3Total / 1000000;
  const pesoCubado = volumeM3Total * transp.fator_cubagem;
  const pesoConsiderado = Math.max(peso, pesoCubado);
  const qualPesa = pesoCubado > peso ? 'cubado' : 'real';
  const totalPaletes = paletes.reduce((soma, p) => soma + p.quantidade, 0);

  cubagemInfo.className = 'cep-info ok';
  cubagemInfo.textContent =
    `Volume total: ${volumeM3Total.toFixed(3)} m³ (${totalPaletes} palete${totalPaletes > 1 ? 's' : ''}) — ` +
    `Cubagem: ${pesoCubado.toFixed(2)} kg (fator ${transp.fator_cubagem} do transporte "${transp.nome}") — ` +
    `peso considerado no cálculo: ${pesoConsiderado.toFixed(2)} kg (peso ${qualPesa}).`;
}

// Caminho inverso: cliente só passou a cubagem (volume em m³) — mostramos
// como sugestão uma caixa cúbica (lados iguais) equivalente a esse volume,
// só de referência. Não mexe em Comprimento/Largura/Altura nem no cálculo
// do frete: quem quiser usar a sugestão precisa copiar os valores à mão.
function aplicarCubagemManual(){
  const input = document.getElementById('cubagem-manual');
  const info = document.getElementById('cubagem-manual-info');
  const volumeM3 = parseFloat(input.value);
  if(!volumeM3 || volumeM3 <= 0){
    info.textContent = '';
    return;
  }

  const volumeCm3 = volumeM3 * 1000000;
  const lado = Math.cbrt(volumeCm3);
  info.className = 'cep-info ok';
  info.textContent = `Sugestão: caixa cúbica de ${lado.toFixed(2)} × ${lado.toFixed(2)} × ${lado.toFixed(2)} cm (mesmo volume). Copie pros campos acima se quiser usar no cálculo.`;
}
const origemFilialSel = document.getElementById('origem-filial');
const origemEnderecoWrap = document.getElementById('origem-endereco-wrap');
const destinoFilialSel = document.getElementById('destino-filial');
const destinoEnderecoWrap = document.getElementById('destino-endereco-wrap');
const campoColeta = document.getElementById('campo-coleta');
const distanciaColetaInput = document.getElementById('distancia_coleta');
const pedagioInput = document.getElementById('pedagio');
const campoPedagio = document.getElementById('campo-pedagio');

const origemTerceirizadaWrap = document.getElementById('origem-terceirizada-wrap');
const origemTransportadoraSel = document.getElementById('origem-transportadora');
const origemTransportadoraInfo = document.getElementById('origem-transportadora-info');
const destinoTerceirizadaWrap = document.getElementById('destino-terceirizada-wrap');
const destinoTransportadoraSel = document.getElementById('destino-transportadora');
const destinoTransportadoraInfo = document.getElementById('destino-transportadora-info');
const destinoRetornoWrap = document.getElementById('destino-retorno-wrap');
const destinoRetornoInfo = document.getElementById('destino-retorno-info');
const destinoRetornoFilialSel = document.getElementById('destino-retorno-filial');
const distanciaRetornoInput = document.getElementById('distancia_retorno');
// Endereço de entrega já resolvido na última vez que "Calcular distância"
// rodou — guardado aqui (fora do handler do botão) porque o seletor de
// filial de retorno precisa dele de novo quando o usuário troca a filial
// manualmente, pra recalcular a distância até a filial escolhida.
let destinoEfetivoEnderecoResolvido = '';
// KM do último trecho (filial mais próxima -> endereço do cliente) quando a
// entrega é terceirizada -- não entra no cálculo do frete (o custo é o valor
// fixo da transportadora), só é exibido informativamente no detalhamento.
let distanciaEntregaTerceirizadaKm = 0;
// KM do último trecho (endereço do cliente -> filial mais próxima) quando a
// entrega é feita pela frota própria direto no cliente -- vem da mesma
// resolução usada pra sugerir a filial de retorno vazio (ver
// calcularDistanciaEEndereco). Não existe uma distância de entrega separada
// de verdade no cálculo (o trecho todo filial-origem -> cliente é uma rota
// só, ver "distancia_km"); esse valor só serve pra estimar, no
// detalhamento, quanto desse trecho é "transferência" e quanto é "entrega"
// (proporção por km), sem mudar nenhum valor usado no cálculo do frete.
let distanciaEntregaPropriaKm = 0;

async function carregarFiliais(){
  const res = await fetch(`${API_BASE}/parametros/filiais`);
  if(!res.ok) throw new Error(`Erro HTTP ${res.status}`);
  filiaisCache = await res.json();
  preencherOpcoes(origemFilialSel, filiaisCache);
  preencherOpcoes(destinoFilialSel, filiaisCache);
  preencherOpcoes(destinoRetornoFilialSel, filiaisCache);
}

async function carregarTransportadoras(){
  const res = await fetch(`${API_BASE}/parametros/transportadoras-terceirizadas`);
  if(!res.ok) throw new Error(`Erro HTTP ${res.status}`);
  transportadorasCache = await res.json();
  preencherSelectTransportadoras(origemTransportadoraSel, 'coleta');
  preencherSelectTransportadoras(destinoTransportadoraSel, 'entrega');
}

function preencherSelectTransportadoras(selectEl, tipo){
  const opcoes = transportadorasCache.filter(t => t.tipo === tipo || t.tipo === 'ambos');
  selectEl.replaceChildren();
  if(opcoes.length === 0){
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = 'Nenhuma transportadora cadastrada';
    selectEl.appendChild(opt);
    return;
  }
  opcoes.forEach(t => {
    const opt = document.createElement('option');
    opt.value = String(t.id);
    opt.textContent = `${t.nome} — ${t.cidade} (${fmtBRL(t.valor)})`;
    selectEl.appendChild(opt);
  });
}

function transportadoraSelecionada(selectEl){
  const id = selectEl.value;
  if(!id) return null;
  return transportadorasCache.find(t => String(t.id) === id) || null;
}

function enderecoDaFilial(nome){
  const f = filiaisCache.find(x => x.nome === nome);
  return f ? f.endereco : '';
}

function formatarCep(v){
  const digitos = v.replace(/\D/g, '').slice(0, 8);
  return digitos.length > 5 ? `${digitos.slice(0,5)}-${digitos.slice(5)}` : digitos;
}

async function buscarCep(cep){
  const limpo = cep.replace(/\D/g, '');
  if(limpo.length !== 8) return null;
  const res = await fetch(`https://viacep.com.br/ws/${limpo}/json/`);
  if(!res.ok) throw new Error('Falha ao consultar o CEP.');
  const data = await res.json();
  if(data.erro) return null;
  return data;
}

function montarEnderecoPorCep(resolvido, numero){
  if(!resolvido) return '';
  let linha1 = resolvido.logradouro || '';
  if(numero) linha1 += (linha1 ? ', ' : '') + numero;
  const partes = [linha1, resolvido.bairro, `${resolvido.localidade} - ${resolvido.uf}`];
  return partes.filter(Boolean).join(', ');
}

// Considera "formato de CEP" quando o texto só tem dígitos/espaço/hífen
// e, ao remover tudo que não é dígito, sobram exatamente 8 números.
function pareceCep(valor){
  const bruto = valor.trim();
  if(!bruto) return false;
  if(!/^[\d\s.-]+$/.test(bruto)) return false;
  return bruto.replace(/\D/g, '').length === 8;
}

function configurarEnderecoCep(prefixo){
  const enderecoInput = document.getElementById(`${prefixo}-endereco-input`);
  const numeroInput = document.getElementById(`${prefixo}-numero`);
  const infoDiv = document.getElementById(`${prefixo}-cep-info`);

  // resolvido: { tipo: 'cep'|'completo', dados?: objeto do ViaCEP, endereco: string }
  let resolvido = null;

  enderecoInput.addEventListener('input', () => {
    if(pareceCep(enderecoInput.value) || /^[\d\s.-]*$/.test(enderecoInput.value)){
      enderecoInput.value = formatarCep(enderecoInput.value);
    }
    infoDiv.className = 'cep-info';
    infoDiv.textContent = '';
    numeroInput.style.display = 'none';
    resolvido = null;
  });

  numeroInput.addEventListener('blur', () => {
    if(resolvido && resolvido.tipo === 'cep'){
      resolvido.endereco = montarEnderecoPorCep(resolvido.dados, numeroInput.value.trim());
      infoDiv.textContent = `Endereço encontrado: ${resolvido.endereco}`;
    }
  });

  async function processarEndereco(){
    const bruto = enderecoInput.value.trim();
    resolvido = null;
    infoDiv.className = 'cep-info';

    if(!bruto){
      infoDiv.textContent = '';
      numeroInput.style.display = 'none';
      return;
    }

    if(pareceCep(bruto)){
      numeroInput.style.display = '';
      infoDiv.textContent = 'Buscando CEP...';
      try{
        const dados = await buscarCep(bruto);
        if(!dados){
          infoDiv.classList.add('err');
          infoDiv.textContent = 'CEP não encontrado. Confira o número ou digite o endereço completo.';
          return;
        }
        const endereco = montarEnderecoPorCep(dados, numeroInput.value.trim());
        resolvido = {tipo: 'cep', dados, endereco};
        infoDiv.classList.add('ok');
        infoDiv.textContent = `Endereço encontrado: ${endereco}`;
      }catch(e){
        infoDiv.classList.add('err');
        infoDiv.textContent = 'Falha ao consultar o CEP. Tente novamente ou digite o endereço completo.';
      }
    }else{
      numeroInput.style.display = 'none';
      resolvido = {tipo: 'completo', endereco: bruto};
      infoDiv.classList.add('ok');
      infoDiv.textContent = `Endereço informado: ${bruto}`;
    }
  }

  enderecoInput.addEventListener('blur', processarEndereco);

  return {
    async obterEndereco(){
      if(!resolvido && enderecoInput.value.trim()){
        await processarEndereco();
      }
      return resolvido ? resolvido.endereco : '';
    },
  };
}

const origemEnderecoCtrl = configurarEnderecoCep('origem');
const destinoEnderecoCtrl = configurarEnderecoCep('destino');

let origemTipo = 'filial';
let destinoTipo = 'filial';
let origemModo = 'propria';
let destinoModo = 'propria';

function configurarToggle(containerId, onChange){
  const container = document.getElementById(containerId);
  container.querySelectorAll('.seg-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      container.querySelectorAll('.seg-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      onChange(btn.dataset.value);
    });
  });
}

configurarToggle('seg-origem', (valor) => {
  origemTipo = valor;
  origemFilialSel.style.display = valor === 'filial' ? '' : 'none';
  origemEnderecoWrap.style.display = valor === 'retirada' ? '' : 'none';
  campoColeta.style.display = (valor === 'retirada' && origemModo === 'propria') ? '' : 'none';
  if(valor === 'filial'){ distanciaColetaInput.value = 0; }
  invalidarRotaCalculada();
});

function resetarRetornoVazio(){
  distanciaRetornoInput.value = 0;
  destinoRetornoWrap.style.display = 'none';
  destinoRetornoFilialSel.value = '';
  destinoRetornoInfo.textContent = '';
  destinoEfetivoEnderecoResolvido = '';
  distanciaEntregaPropriaKm = 0;
}

// Usuário trocou manualmente a filial de retorno (o auto-sugerido nem
// sempre é pra onde o veículo realmente volta) — recalcula a distância
// vazia até a filial escolhida.
destinoRetornoFilialSel.addEventListener('change', async () => {
  const filial = destinoRetornoFilialSel.value;
  if(!filial || !destinoEfetivoEnderecoResolvido){
    return;
  }
  const enderecoFilial = enderecoDaFilial(filial);
  if(!enderecoFilial){
    return;
  }
  destinoRetornoInfo.className = 'cep-info';
  destinoRetornoInfo.textContent = `Calculando distância até ${filial}...`;
  try{
    const res = await fetch(`${API_BASE}/geo/distancia`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({origem: enderecoFilial, destino: destinoEfetivoEnderecoResolvido}),
    });
    const data = await res.json();
    if(!res.ok) throw new Error(data.detail || 'Não foi possível calcular a distância.');
    distanciaRetornoInput.value = data.distancia_km;
    destinoRetornoInfo.classList.add('ok');
    destinoRetornoInfo.textContent = `Retorno vazio até ${filial}: ${data.distancia_km} km.`;
  }catch(e){
    destinoRetornoInfo.classList.add('err');
    destinoRetornoInfo.textContent = `Não foi possível calcular a distância até ${filial}: ${e.message}`;
  }
});

configurarToggle('seg-destino', (valor) => {
  destinoTipo = valor;
  destinoFilialSel.style.display = valor === 'filial' ? '' : 'none';
  destinoEnderecoWrap.style.display = valor === 'cliente' ? '' : 'none';
  resetarRetornoVazio();
  invalidarRotaCalculada();
});

configurarToggle('seg-origem-modo', (valor) => {
  origemModo = valor;
  origemTerceirizadaWrap.style.display = valor === 'terceirizada' ? '' : 'none';
  campoColeta.style.display = (origemTipo === 'retirada' && valor === 'propria') ? '' : 'none';
  invalidarRotaCalculada();
});

configurarToggle('seg-destino-modo', (valor) => {
  destinoModo = valor;
  destinoTerceirizadaWrap.style.display = valor === 'terceirizada' ? '' : 'none';
  resetarRetornoVazio();
  invalidarRotaCalculada();
});

['peso', 'comprimento', 'largura', 'altura', 'quantidade'].forEach(id => {
  document.getElementById(id).addEventListener('input', atualizarCubagem);
});
document.getElementById('transporte').addEventListener('change', atualizarCubagem);
document.getElementById('cubagem-manual').addEventListener('input', aplicarCubagemManual);

inicializarFormulario();
verificarSessao();

const btnGeo = document.getElementById('btn-geo');
const geoStatus = document.getElementById('geo-status');
const distanciaInput = document.getElementById('distancia');
let cidadeColetaResolvida = '';
let cidadeOrigemResolvida = '';
let cidadeDestinoResolvida = '';
let prioridadeRotaResolvida = '';

// Flag (não o valor do campo) que diz se a rota calculada ainda vale --
// o campo "distancia" é required no HTML, então esvaziá-lo pra marcar
// "precisa recalcular" faz o navegador bloquear o submit sozinho (antes
// do JS rodar) com a mensagem nativa de campo obrigatório. Por isso o
// estado fica só nessa variável; o campo mantém o último número visível
// (ainda que desatualizado) até um novo cálculo.
let rotaValida = false;

// Rota calculada fica obsoleta assim que o usuário muda origem, destino
// ou o endereço digitado -- marca rotaValida=false pra "Calcular frete"
// saber que precisa recalcular (ver uso de rotaValida no submit, mais
// abaixo), em vez de reenviar silenciosamente a rota antiga -- ex: manter
// a taxa de balsa de Belém depois de trocar a origem pra São Paulo.
function invalidarRotaCalculada(){
  rotaValida = false;
  cidadeColetaResolvida = '';
  cidadeOrigemResolvida = '';
  cidadeDestinoResolvida = '';
  prioridadeRotaResolvida = '';
  distanciaEntregaTerceirizadaKm = 0;
  distanciaEntregaPropriaKm = 0;
  geoStatus.className = 'geo-status';
  geoStatus.textContent = '';
}
origemFilialSel.addEventListener('change', invalidarRotaCalculada);
destinoFilialSel.addEventListener('change', invalidarRotaCalculada);
document.getElementById('origem-endereco-input').addEventListener('input', invalidarRotaCalculada);
document.getElementById('destino-endereco-input').addEventListener('input', invalidarRotaCalculada);

// Extraído do listener de clique do botão "Calcular distância" pra
// poder ser chamado também no submit de "Calcular frete", sem exigir
// que o usuário clique nos dois botões em sequência (ver uso abaixo).
// Devolve true/false em vez de deixar o erro subir, porque quem chama
// (o submit do formulário) decide o que fazer com a falha.
async function calcularDistanciaEEndereco(){
  geoStatus.className = 'geo-status';
  geoStatus.textContent = '';
  rotaValida = false;
  cidadeColetaResolvida = '';
  cidadeOrigemResolvida = '';
  cidadeDestinoResolvida = '';
  prioridadeRotaResolvida = '';
  distanciaEntregaTerceirizadaKm = 0;
  distanciaEntregaPropriaKm = 0;

  btnGeo.disabled = true;
  btnGeo.textContent = 'Calculando...';
  geoStatus.textContent = 'Consultando endereços...';

  try{
    let origemEfetivaEndereco;
    let mensagemColeta = '';

    if(origemTipo === 'retirada'){
      const enderecoRetirada = await origemEnderecoCtrl.obterEndereco();
      if(!enderecoRetirada){
        throw new Error('Informe o CEP ou o endereço completo de retirada.');
      }
      const res = await fetch(`${API_BASE}/geo/resolver-retirada`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({endereco_retirada: enderecoRetirada}),
      });
      const data = await res.json();
      if(!res.ok){
        throw new Error(data.detail || 'Não foi possível localizar a filial mais próxima.');
      }
      distanciaColetaInput.value = data.distancia_coleta_km;
      origemEfetivaEndereco = data.filial_endereco;
      cidadeColetaResolvida = data.endereco_resolvido || '';
      cidadeOrigemResolvida = data.filial_mais_proxima || '';
      mensagemColeta = `Filial mais próxima: ${data.filial_mais_proxima} (coleta: ${data.distancia_coleta_km} km). `;
    }else{
      origemEfetivaEndereco = enderecoDaFilial(origemFilialSel.value);
      distanciaColetaInput.value = 0;
      cidadeOrigemResolvida = origemFilialSel.value;
    }

    let destinoEfetivoEndereco;
    if(destinoTipo === 'filial'){
      destinoEfetivoEndereco = enderecoDaFilial(destinoFilialSel.value);
      cidadeDestinoResolvida = destinoFilialSel.value;
    }else if(destinoModo === 'terceirizada'){
      const enderecoEntrega = await destinoEnderecoCtrl.obterEndereco();
      if(!enderecoEntrega){
        throw new Error('Informe o CEP ou o endereço completo de entrega.');
      }
      const resEnt = await fetch(`${API_BASE}/geo/resolver-entrega`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({endereco_entrega: enderecoEntrega}),
      });
      const dataEnt = await resEnt.json();
      if(!resEnt.ok){
        throw new Error(dataEnt.detail || 'Não foi possível localizar a filial mais próxima da entrega.');
      }
      // Com entrega terceirizada, a rota principal (frota própria) vai só
      // até a filial mais próxima do cliente — o trecho final fica com a
      // transportadora contratada.
      destinoEfetivoEndereco = dataEnt.filial_endereco;
      cidadeDestinoResolvida = dataEnt.filial_mais_proxima || '';
      distanciaEntregaTerceirizadaKm = dataEnt.distancia_coleta_km || 0;
      mensagemColeta += `Entrega terceirizada: filial mais próxima do cliente é ${dataEnt.filial_mais_proxima} (${dataEnt.distancia_coleta_km} km até o cliente). `;
    }else{
      destinoEfetivoEndereco = await destinoEnderecoCtrl.obterEndereco();
      if(!destinoEfetivoEndereco){
        throw new Error('Informe o CEP ou o endereço completo de entrega.');
      }
      cidadeDestinoResolvida = destinoEfetivoEndereco;
    }

    // Retorno vazio do veículo: só faz sentido quando a entrega é feita
    // direto ao cliente pela frota própria — nos outros casos (destino é
    // filial, ou entrega terceirizada) o veículo próprio já termina numa
    // filial, sem precurso de retorno vazio.
    if(destinoTipo === 'cliente' && destinoModo === 'propria'){
      destinoEfetivoEnderecoResolvido = destinoEfetivoEndereco;
      const resRet = await fetch(`${API_BASE}/geo/resolver-retorno`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({endereco_destino: destinoEfetivoEndereco}),
      });
      const dataRet = await resRet.json();
      destinoRetornoWrap.style.display = '';
      if(resRet.ok){
        distanciaRetornoInput.value = dataRet.distancia_coleta_km;
        distanciaEntregaPropriaKm = dataRet.distancia_coleta_km || 0;
        destinoRetornoFilialSel.value = dataRet.filial_mais_proxima;
        destinoRetornoInfo.className = 'cep-info ok';
        destinoRetornoInfo.textContent =
          `Sugestão automática: ${dataRet.filial_mais_proxima} (${dataRet.distancia_coleta_km} km vazio) — ` +
          `troque no seletor acima se o veículo voltar pra outra filial.`;
      }else{
        // Não bloqueia o cálculo do frete por isso — só avisa que o
        // retorno não pôde ser estimado automaticamente; o usuário ainda
        // escolhe a filial manualmente no seletor.
        distanciaRetornoInput.value = 0;
        distanciaEntregaPropriaKm = 0;
        destinoRetornoFilialSel.value = '';
        destinoRetornoInfo.className = 'cep-info err';
        destinoRetornoInfo.textContent =
          `Não foi possível sugerir automaticamente (${dataRet.detail || 'endereço não encontrado'}) — escolha a filial de retorno no seletor acima.`;
      }
    }else{
      resetarRetornoVazio();
    }

    const res2 = await fetch(`${API_BASE}/geo/distancia`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        origem: origemEfetivaEndereco, destino: destinoEfetivoEndereco,
        // peso/paletes/transporte aqui não entram no cálculo do frete —
        // só permitem ao backend descobrir o veículo e reaproveitar a
        // distância de uma rota+veículo já cotada no histórico, sem
        // gastar geocodificação de novo.
        peso: pesoParaNumero(document.getElementById('peso').value) || 0,
        paletes: coletarPaletes(),
        transporte: document.getElementById('transporte').value || '',
      }),
    });
    const data2 = await res2.json();
    if(!res2.ok){
      throw new Error(data2.detail || 'Não foi possível calcular a distância.');
    }

    distanciaInput.value = data2.distancia_km;
    prioridadeRotaResolvida = data2.prioridade_rota || '';
    const horas = Math.floor(data2.duracao_min / 60);
    const minutos = Math.round(data2.duracao_min % 60);
    const tempoTexto = horas > 0 ? `${horas}h${minutos.toString().padStart(2,'0')}` : `${minutos} min`;

    let mensagemPedagio = '';
    if(typeof data2.pedagio_valor === 'number'){
      pedagioInput.value = formatarValorMoeda(data2.pedagio_valor);
      campoPedagio.style.display = '';
      // pedagio_pracas só vem preenchido quando o valor saiu do catálogo
      // de praças cadastrado (/admin/pracas-pedagio), não da estimativa
      // genérica do Google -- mais preciso, por isso mostra a composição.
      mensagemPedagio = (data2.pedagio_pracas && data2.pedagio_pracas.length)
        ? ` Pedágio: ${fmtBRL(data2.pedagio_valor)} (${data2.pedagio_pracas.join(', ')}).`
        : ` Pedágio estimado: ${fmtBRL(data2.pedagio_valor)}.`;
    }else{
      campoPedagio.style.display = 'none';
      pedagioInput.value = formatarValorMoeda(0);
    }

    // Rota com prioridade de rota (ver /geo/distancia): a distância acima já
    // vem somada (origem->filial + filial->destino) -- só avisa qual filial
    // entrou no meio do caminho, pra não parecer um km "estranho" sem explicação.
    const mensagemPrioridade = data2.prioridade_rota
      ? ` Rota via ${data2.prioridade_rota} (prioridade de rota).`
      : '';

    geoStatus.classList.add('ok');
    geoStatus.textContent = `${mensagemColeta}Distância do frete: ${data2.distancia_km} km (≈ ${tempoTexto}).${mensagemPrioridade}${mensagemPedagio}`;
    rotaValida = true;
    return true;

  }catch(err){
    geoStatus.classList.add('err');
    geoStatus.textContent = err.message;
    return false;
  }finally{
    btnGeo.disabled = false;
    btnGeo.textContent = 'Calcular distância';
  }
}

btnGeo.addEventListener('click', () => { calcularDistanciaEEndereco(); });

form.addEventListener('submit', async (ev) => {
  ev.preventDefault();
  errorBox.classList.remove('show');
  errorBox.textContent = '';
  stamp.classList.remove('show');
  ultimoOrcamento = null;
  document.getElementById('historico-salvar-status').textContent = '';

  // Se "Calcular distância" ainda não rodou pra essa cotação (ou a rota
  // mudou desde o último cálculo -- ver invalidarRotaCalculada), roda
  // agora -- assim "Calcular frete" funciona num clique só, sem exigir o
  // passo manual antes. Se a rota já está válida (calculada antes ou
  // editada à mão no campo distância), não mexe.
  if(!rotaValida){
    const ok = await calcularDistanciaEEndereco();
    if(!ok){
      errorBox.textContent = 'Não foi possível calcular a distância automaticamente. Confira os endereços informados e clique em "Calcular frete" de novo.';
      errorBox.classList.add('show');
      return;
    }
  }

  const origemColetaTerceirizada = origemTipo === 'retirada' && origemModo === 'terceirizada';
  const destinoEntregaTerceirizada = destinoTipo === 'cliente' && destinoModo === 'terceirizada';
  const transportadoraColeta = origemColetaTerceirizada ? transportadoraSelecionada(origemTransportadoraSel) : null;
  const transportadoraEntrega = destinoEntregaTerceirizada ? transportadoraSelecionada(destinoTransportadoraSel) : null;

  if(origemColetaTerceirizada && !transportadoraColeta){
    errorBox.textContent = 'Selecione a transportadora terceirizada da coleta.';
    errorBox.classList.add('show');
    return;
  }
  if(destinoEntregaTerceirizada && !transportadoraEntrega){
    errorBox.textContent = 'Selecione a transportadora terceirizada da entrega.';
    errorBox.classList.add('show');
    return;
  }
  if(destinoRetornoWrap.style.display !== 'none' && !destinoRetornoFilialSel.value){
    errorBox.textContent = 'Escolha a filial de retorno vazio do veículo (ou clique em "Calcular distância" de novo antes de enviar).';
    errorBox.classList.add('show');
    return;
  }

  const paletes = coletarPaletes();
  if(paletes.some(p => p.comprimento <= 0 || p.largura <= 0 || p.altura <= 0)){
    errorBox.textContent = 'Preencha comprimento, largura e altura de todos os paletes.';
    errorBox.classList.add('show');
    return;
  }

  const payload = {
    peso: pesoParaNumero(document.getElementById('peso').value),
    paletes,
    distancia: parseFloat(document.getElementById('distancia').value),
    distancia_coleta: parseFloat(distanciaColetaInput.value) || 0,
    distancia_retorno: parseFloat(distanciaRetornoInput.value) || 0,
    filial_retorno: destinoRetornoWrap.style.display !== 'none' ? destinoRetornoFilialSel.value : '',
    pedagio: valorMoedaParaNumero(pedagioInput.value),
    cidade_coleta: cidadeColetaResolvida,
    cidade_origem: cidadeOrigemResolvida,
    cidade_destino: cidadeDestinoResolvida,
    prioridade_rota: prioridadeRotaResolvida,
    valor_mercadoria: valorMoedaParaNumero(document.getElementById('valor_mercadoria').value),
    categoria: document.getElementById('categoria').value,
    transporte: document.getElementById('transporte').value,
    sla: document.getElementById('sla').value,
    coleta_terceirizada: origemColetaTerceirizada,
    transportadora_coleta_nome: transportadoraColeta ? transportadoraColeta.nome : '',
    valor_coleta_terceirizada: transportadoraColeta ? transportadoraColeta.valor : 0,
    entrega_terceirizada: destinoEntregaTerceirizada,
    transportadora_entrega_nome: transportadoraEntrega ? transportadoraEntrega.nome : '',
    valor_entrega_terceirizada: transportadoraEntrega ? transportadoraEntrega.valor : 0,
    custos_extras: coletarCustosExtras(),
    gris_pct: parseFloat(document.getElementById('gris_pct').value),
    ad_valorem_pct: parseFloat(document.getElementById('ad_valorem_pct').value),
  };

  btn.disabled = true;
  btn.textContent = 'Calculando...';
  statusTag.textContent = 'Processando';

  try{
    const res = await fetch(`${API_BASE}/orcamento`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    const data = await res.json();

    if(!res.ok){
      throw new Error(data.detail || 'Não foi possível calcular o frete.');
    }

    const calc = data.calculos_intermediarios;
    const result = data.resultado;
    renderizarMemoriaCalculo(data);

    document.getElementById('out-total').textContent = fmtBRL(result.frete_total);
    document.getElementById('out-veiculo').textContent = data.entrada.veiculo;
    document.getElementById('out-prazo').textContent = `${result.prazo_estimado_dias_uteis} dias úteis`;
    document.getElementById('d-peso').textContent = `${calc.peso_considerado_kg} kg`;

    const linhaVolume = document.getElementById('linha-volume');
    if(calc.capacidade_util_m3_veiculo > 0){
      linhaVolume.style.display = '';
      document.getElementById('d-volume').textContent =
        `${calc.volume_total_m3} m³ de ${calc.capacidade_disponivel_m3_veiculo} m³ disponíveis ` +
        `(${calc.capacidade_ocupada_pct}% dos ${calc.percentual_capacidade_util_veiculo}% permitidos)`;
    }else{
      linhaVolume.style.display = 'none';
    }

    const linhaKmColeta = document.getElementById('linha-km-coleta');
    if(data.entrada.distancia_coleta_km > 0){
      document.getElementById('d-km-coleta').textContent = `${data.entrada.distancia_coleta_km} km`;
      linhaKmColeta.style.display = 'flex';
    }else{
      linhaKmColeta.style.display = 'none';
    }

    // Quando a entrega é própria e direto no cliente, o trecho principal
    // (data.entrada.distancia_km) já embute transferência + entrega numa
    // rota só -- não existe uma distância de entrega calculada de verdade
    // separada. distanciaEntregaPropriaKm (mesma resolução usada pra
    // sugerir a filial de retorno vazio) serve só de estimativa pra
    // mostrar essa proporção no detalhamento, sem mudar nenhum valor do
    // cálculo em si.
    //
    // distancia_km inclui o trecho de balsa (ex: Belém -> Manaus), que o
    // veículo não roda -- exclui esse km antes de exibir "KM de
    // transferência", senão parece que a frota rodou estrada onde na
    // verdade foi de balsa (a travessia já aparece à parte em "Taxa de
    // balsa aplicada").
    const distanciaRodadaTotal = Math.max(data.entrada.distancia_km - (calc.distancia_balsa_km || 0), 0);
    const kmEntregaPropriaEstimado = Math.min(distanciaEntregaPropriaKm, distanciaRodadaTotal);
    const kmTransferencia = kmEntregaPropriaEstimado > 0
      ? Math.max(distanciaRodadaTotal - kmEntregaPropriaEstimado, 0)
      : distanciaRodadaTotal;
    document.getElementById('d-km-transferencia').textContent = `${kmTransferencia} km`;

    const linhaKmEntrega = document.getElementById('linha-km-entrega');
    const kmEntregaExibir = kmEntregaPropriaEstimado > 0 ? kmEntregaPropriaEstimado : distanciaEntregaTerceirizadaKm;
    if(kmEntregaExibir > 0){
      document.getElementById('d-km-entrega').textContent = `${kmEntregaExibir} km`;
      linhaKmEntrega.style.display = 'flex';
    }else{
      linhaKmEntrega.style.display = 'none';
    }

    const linhaKmRetorno = document.getElementById('linha-km-retorno');
    if(calc.distancia_retorno_km > 0){
      document.getElementById('d-km-retorno').textContent = `${calc.distancia_retorno_km} km`;
      linhaKmRetorno.style.display = 'flex';
    }else{
      linhaKmRetorno.style.display = 'none';
    }

    document.getElementById('d-custo-km').textContent = fmtBRL(calc.custo_km);
    document.getElementById('d-peso-exc').textContent = `${calc.peso_excedente_kg} kg`;
    document.getElementById('d-custo-peso-exc').textContent = fmtBRL(calc.custo_peso_excedente);
    document.getElementById('d-base').textContent = fmtBRL(calc.frete_base);
    document.getElementById('d-ajustado').textContent = fmtBRL(calc.frete_ajustado);

    // Custo de entrega própria estimado (proporcional aos km) -- quebra o
    // mesmo "Frete ajustado" acima entre transferência e entrega, só pra
    // exibição; a soma das duas partes é sempre igual ao frete ajustado.
    const linhaCustoTransferencia = document.getElementById('linha-custo-transferencia');
    const linhaCustoEntregaPropria = document.getElementById('linha-custo-entrega-propria');
    if(kmEntregaPropriaEstimado > 0 && distanciaRodadaTotal > 0){
      const proporcaoEntrega = kmEntregaPropriaEstimado / distanciaRodadaTotal;
      const custoEntregaEstimado = calc.frete_ajustado * proporcaoEntrega;
      document.getElementById('d-custo-transferencia').textContent = fmtBRL(calc.frete_ajustado - custoEntregaEstimado);
      document.getElementById('d-custo-entrega-propria').textContent = fmtBRL(custoEntregaEstimado);
      linhaCustoTransferencia.style.display = 'flex';
      linhaCustoEntregaPropria.style.display = 'flex';
    }else{
      linhaCustoTransferencia.style.display = 'none';
      linhaCustoEntregaPropria.style.display = 'none';
    }

    const linhaColeta = document.getElementById('linha-coleta');
    if(calc.custo_coleta > 0){
      let rotuloColeta = 'Taxa de coleta (por km)';
      if(calc.coleta_terceirizada){
        rotuloColeta = `Coleta terceirizada (${calc.transportadora_coleta_nome})`;
      }else if(calc.coleta_fixa_por_cidade){
        rotuloColeta = 'Taxa de coleta (preço fixo por cidade)';
      }
      document.getElementById('linha-coleta').querySelector('span').textContent = rotuloColeta;
      document.getElementById('d-coleta').textContent = fmtBRL(calc.custo_coleta);
      linhaColeta.style.display = 'flex';
    }else{
      linhaColeta.style.display = 'none';
    }

    const linhaEntregaTerc = document.getElementById('linha-entrega-terceirizada');
    if(calc.custo_entrega_terceirizada > 0){
      document.getElementById('linha-entrega-terceirizada').querySelector('span').textContent =
        `Entrega terceirizada (${calc.transportadora_entrega_nome})`;
      document.getElementById('d-entrega-terceirizada').textContent = fmtBRL(calc.custo_entrega_terceirizada);
      linhaEntregaTerc.style.display = 'flex';
    }else{
      linhaEntregaTerc.style.display = 'none';
    }

    const linhaPedagio = document.getElementById('linha-pedagio');
    if(calc.pedagio > 0){
      linhaPedagio.querySelector('span').textContent = calc.pedagio_estimado_pct
        ? `Pedágio (estimado, ${calc.pedagio_estimado_pct}% do frete)` : 'Pedágio';
      document.getElementById('d-pedagio').textContent = fmtBRL(calc.pedagio);
      linhaPedagio.style.display = 'flex';
    }else{
      linhaPedagio.style.display = 'none';
    }

    const linhaManutencao = document.getElementById('linha-manutencao');
    if(calc.custo_manutencao > 0){
      document.getElementById('d-manutencao').textContent = fmtBRL(calc.custo_manutencao);
      linhaManutencao.style.display = 'flex';
    }else{
      linhaManutencao.style.display = 'none';
    }

    const linhaRetorno = document.getElementById('linha-retorno');
    if(calc.custo_retorno > 0){
      document.getElementById('d-retorno').textContent = fmtBRL(calc.custo_retorno);
      linhaRetorno.style.display = 'flex';
    }else{
      linhaRetorno.style.display = 'none';
    }

    const linhaTaxasRegionais = document.getElementById('linha-taxas-regionais');
    if(calc.custo_taxas_regionais > 0){
      const nomesTaxasRegionais = (calc.taxas_regionais || []).map(t => `${t.nome} (${t.cidade})`).join(', ');
      document.getElementById('d-taxas-regionais').textContent = fmtBRL(calc.custo_taxas_regionais);
      document.getElementById('linha-taxas-regionais').title = nomesTaxasRegionais;
      linhaTaxasRegionais.style.display = 'flex';
    }else{
      linhaTaxasRegionais.style.display = 'none';
    }

    const linhaTaxaBalsa = document.getElementById('linha-taxa-balsa');
    if(calc.custo_balsa > 0 && (calc.taxa_balsa || calc.taxa_balsa_retorno)){
      document.getElementById('d-taxa-balsa').textContent = fmtBRL(calc.custo_balsa);
      // Balsa é cobrada em cada travessia (ida e volta são taxas
      // cadastradas independentes, ver frete_service.calcular_orcamento)
      // -- quando o retorno vazio também cruza balsa, o tooltip mostra
      // os dois trechos, não só o da ida.
      const trechos = [];
      if(calc.taxa_balsa) trechos.push(`${calc.taxa_balsa.cidade_origem} → ${calc.taxa_balsa.cidade_destino} (${calc.taxa_balsa.veiculo})`);
      if(calc.taxa_balsa_retorno) trechos.push(`retorno: ${calc.taxa_balsa_retorno.cidade_origem} → ${calc.taxa_balsa_retorno.cidade_destino} (${calc.taxa_balsa_retorno.veiculo})`);
      linhaTaxaBalsa.title = trechos.join(' + ');
      linhaTaxaBalsa.style.display = 'flex';
    }else{
      linhaTaxaBalsa.style.display = 'none';
    }

    const linhaDiariaVeiculo = document.getElementById('linha-diaria-veiculo');
    if(calc.custo_diaria_veiculo > 0 && calc.diaria_veiculo){
      document.getElementById('d-diaria-veiculo').textContent = fmtBRL(calc.custo_diaria_veiculo);
      linhaDiariaVeiculo.title =
        `${calc.diaria_veiculo.uf}: carreta ${fmtBRL(calc.diaria_veiculo.valor_carreta)} + cavalo ${fmtBRL(calc.diaria_veiculo.valor_cavalo)}`;
      linhaDiariaVeiculo.style.display = 'flex';
    }else{
      linhaDiariaVeiculo.style.display = 'none';
    }

    // GRIS e Ad Valorem (ver gris_pct/ad_valorem_pct) ganham linha própria
    // em Impostos e taxas, em vez de ficarem só somados dentro de "Taxas
    // adicionais" -- as outras taxas cadastradas (se houver) continuam
    // juntas ali, sem repetir GRIS/Ad Valorem duas vezes na tela.
    const taxasAdicionaisLista = calc.taxas_adicionais || [];
    const taxaGris = taxasAdicionaisLista.find(t => t.nome.trim().toLowerCase() === 'gris');
    const taxaAdValorem = taxasAdicionaisLista.find(t => t.nome.trim().toLowerCase() === 'ad valorem');
    const outrasTaxasAdicionais = taxasAdicionaisLista.filter(t => {
      const chave = t.nome.trim().toLowerCase();
      return chave !== 'gris' && chave !== 'ad valorem';
    });

    const linhaGris = document.getElementById('linha-gris');
    if(taxaGris && taxaGris.valor_aplicado > 0){
      document.getElementById('d-gris').textContent = `${fmtBRL(taxaGris.valor_aplicado)} (${taxaGris.valor_configurado}%)`;
      linhaGris.style.display = 'flex';
    }else{
      linhaGris.style.display = 'none';
    }

    const linhaAdValorem = document.getElementById('linha-ad-valorem');
    if(taxaAdValorem && taxaAdValorem.valor_aplicado > 0){
      document.getElementById('d-ad-valorem').textContent = `${fmtBRL(taxaAdValorem.valor_aplicado)} (${taxaAdValorem.valor_configurado}%)`;
      linhaAdValorem.style.display = 'flex';
    }else{
      linhaAdValorem.style.display = 'none';
    }

    const custoOutrasTaxasAdicionais = outrasTaxasAdicionais.reduce((soma, t) => soma + t.valor_aplicado, 0);
    const linhaTaxas = document.getElementById('linha-taxas');
    const blocoDetalheTaxas = document.getElementById('bloco-detalhe-taxas');
    if(custoOutrasTaxasAdicionais > 0){
      document.getElementById('d-taxas').textContent = fmtBRL(custoOutrasTaxasAdicionais);
      linhaTaxas.style.display = 'flex';
      const listaDetalhe = document.getElementById('lista-detalhe-taxas');
      listaDetalhe.innerHTML = outrasTaxasAdicionais.map(t => {
        const rotulo = t.tipo === 'percentual' ? `${esc(t.nome)} (${t.valor_configurado}%)` : esc(t.nome);
        return `<div class="line"><span>${rotulo}</span><span>${fmtBRL(t.valor_aplicado)}</span></div>`;
      }).join('');
      blocoDetalheTaxas.style.display = 'block';
    }else{
      linhaTaxas.style.display = 'none';
      blocoDetalheTaxas.style.display = 'none';
    }

    const linhaCustosExtras = document.getElementById('linha-custos-extras');
    const blocoDetalheCustosExtras = document.getElementById('bloco-detalhe-custos-extras');
    if(calc.custo_extra_total > 0){
      document.getElementById('d-custos-extras').textContent = fmtBRL(calc.custo_extra_total);
      linhaCustosExtras.style.display = 'flex';
      document.getElementById('lista-detalhe-custos-extras').innerHTML = (calc.custos_extras || []).map(c =>
        `<div class="line"><span>${esc(c.categoria)}</span><span>${fmtBRL(c.valor_aplicado)}</span></div>`
      ).join('');
      blocoDetalheCustosExtras.style.display = 'block';
    }else{
      linhaCustosExtras.style.display = 'none';
      blocoDetalheCustosExtras.style.display = 'none';
    }

    const linhaMargemLucro = document.getElementById('linha-margem-lucro');
    if(calc.valor_margem_lucro > 0){
      document.getElementById('d-margem-lucro').textContent = `${fmtBRL(calc.valor_margem_lucro)} (${calc.margem_lucro_pct}%)`;
      linhaMargemLucro.style.display = 'flex';
    }else{
      linhaMargemLucro.style.display = 'none';
    }

    const linhaAjustePiso = document.getElementById('linha-ajuste-piso');
    if(calc.ajuste_piso_markup > 0){
      document.getElementById('d-ajuste-piso').textContent = fmtBRL(calc.ajuste_piso_markup);
      linhaAjustePiso.style.display = 'flex';
    }else{
      linhaAjustePiso.style.display = 'none';
    }

    const linhaPisCofins = document.getElementById('linha-pis-cofins');
    if(calc.valor_pis_cofins > 0){
      document.getElementById('d-pis-cofins').textContent = fmtBRL(calc.valor_pis_cofins);
      linhaPisCofins.title = `${calc.aliquota_pis_cofins_pct}%, aplicado por dentro sobre ${fmtBRL(calc.frete_sem_pis_cofins)}`;
      linhaPisCofins.style.display = 'flex';
    }else{
      linhaPisCofins.style.display = 'none';
    }

    const linhaIcms = document.getElementById('linha-icms');
    if(calc.valor_icms > 0){
      document.getElementById('d-icms').textContent = fmtBRL(calc.valor_icms);
      linhaIcms.title = `${calc.uf_origem_icms} → ${calc.uf_destino_icms} (${calc.aliquota_icms_pct}% somado por fora sobre ${fmtBRL(calc.frete_sem_icms)}, já com a margem de lucro embutida)`;
      linhaIcms.style.display = 'flex';
    }else{
      linhaIcms.style.display = 'none';
    }

    // Subtotais agrupados (ver frete_service.calcular_orcamento): custo da
    // operação (transporte em si) x impostos e taxas, depois PIS/COFINS e
    // a margem de lucro por cima dessa soma, e o ICMS entra por último —
    // % simples sobre o preço já com a margem embutida, não sobre um
    // custo intermediário antes do lucro.
    document.getElementById('d-total-operacao').textContent = fmtBRL(calc.total_custo_operacao);
    document.getElementById('d-total-impostos-taxas').textContent = fmtBRL(calc.total_impostos_taxas);
    document.getElementById('d-operacao-mais-impostos').textContent = fmtBRL(calc.frete_sem_pis_cofins);
    document.getElementById('d-total-antes-icms').textContent = fmtBRL(calc.frete_sem_icms);

    document.getElementById('d-total').textContent = fmtBRL(result.frete_total);

    resultEmpty.style.display = 'none';
    resultContent.style.display = 'block';
    requestAnimationFrame(() => stamp.classList.add('show'));
    statusTag.textContent = 'Calculado';

    ultimoOrcamento = {payload, resultado: data};

  }catch(err){
    errorBox.textContent = err.message;
    errorBox.classList.add('show');
    statusTag.textContent = 'Erro';
  }finally{
    btn.disabled = false;
    btn.textContent = 'Calcular frete';
  }
});

document.getElementById('toggle-servico').addEventListener('click', () => {
  const bloco = document.getElementById('bloco-servico');
  const icon = document.getElementById('icon-servico');
  const abrindo = bloco.style.display === 'none';
  bloco.style.display = abrindo ? '' : 'none';
  icon.classList.toggle('ti-chevron-right', !abrindo);
  icon.classList.toggle('ti-chevron-down', abrindo);
});

// Categorias de custo extra marcadas nesse orçamento (multiselect via
// botões que ligam/desligam "active") -- cada uma marcada ganha uma linha
// com campo de valor (R$) digitado na hora, sem catálogo pré-cadastrado
// (ver frete_service.CATEGORIAS_CUSTO_EXTRA). coletarCustosExtras() lê o
// estado atual na hora de montar o payload do cálculo.
const listaValoresCustosExtras = document.getElementById('lista-valores-custos-extras');
function idValorCustoExtra(categoria){
  return `custo-extra-valor-${categoria.replace(/\s+/g, '-')}`;
}
document.getElementById('custos-extras-categorias').addEventListener('click', (ev) => {
  const btn = ev.target.closest('.seg-btn');
  if(!btn) return;
  const categoria = btn.dataset.categoria;
  const ativo = btn.classList.toggle('active');
  const linhaId = idValorCustoExtra(categoria);
  if(ativo){
    const div = document.createElement('div');
    div.className = 'field';
    div.id = linhaId;
    div.innerHTML = `
      <div class="idx">·</div>
      <div>
        <label>${esc(categoria)} (R$)</label>
        <input type="text" inputmode="decimal" value="0,00" oninput="formatarMoedaDigitando(this)">
      </div>
    `;
    listaValoresCustosExtras.appendChild(div);
  }else{
    document.getElementById(linhaId)?.remove();
  }
});

function coletarCustosExtras(){
  return [...document.querySelectorAll('#custos-extras-categorias .seg-btn.active')].map(btn => {
    const categoria = btn.dataset.categoria;
    const input = document.getElementById(idValorCustoExtra(categoria))?.querySelector('input');
    return {categoria, valor: valorMoedaParaNumero(input ? input.value : '0')};
  });
}

// ============================================================
// Cotação Fracionado
// ============================================================
// Mesma lógica do formulário principal (categoria/transporte/SLA, taxas
// adicionais/regionais, balsa, ICMS, PIS/COFINS, margem de lucro — ver
// frete_service.calcular_orcamento_fracionado), mas o frete base vem de
// faixa de peso + faixa de distância em vez de veículo escolhido pelo
// peso. Primeira versão só cobre transferência entre filiais (sem CEP de
// coleta/entrega no cliente, sem terceirizada, sem retorno vazio) — por
// isso o formulário é mais enxuto que o principal, reaproveitando os
// caches já carregados por ele (filiaisCache, transportesCache) em vez
// de buscar tudo de novo.
let fracInicializado = false;
let fracUltimoOrcamento = null;
let fracRotaValida = false;
let fracCidadeOrigemResolvida = '';
let fracCidadeDestinoResolvida = '';
let fracPrioridadeRotaResolvida = '';

function fracColetarPaletes(){
  const comprimentos = document.querySelectorAll('.frac-palete-comprimento');
  const larguras = document.querySelectorAll('.frac-palete-largura');
  const alturas = document.querySelectorAll('.frac-palete-altura');
  const quantidades = document.querySelectorAll('.frac-palete-quantidade');
  return Array.from(comprimentos).map((el, i) => ({
    comprimento: parseFloat(el.value) || 0,
    largura: parseFloat(larguras[i].value) || 0,
    altura: parseFloat(alturas[i].value) || 0,
    quantidade: parseInt(quantidades[i].value, 10) || 1,
  }));
}

function fracCriarLinhaPalete(){
  const wrap = document.getElementById('frac-paletes-extra');
  const row = document.createElement('div');
  row.className = 'row2 row2-palete palete-row';
  row.innerHTML = `
    <div class="field">
      <div class="idx">+</div>
      <div><label>Comprimento (cm)</label><input type="number" class="frac-palete-comprimento" min="0.1" step="0.01" value="100" required></div>
    </div>
    <div class="field">
      <div class="idx">+</div>
      <div><label>Largura (cm)</label><input type="number" class="frac-palete-largura" min="0.1" step="0.01" value="100" required></div>
    </div>
    <div class="field">
      <div class="idx">+</div>
      <div><label>Altura (cm)</label><input type="number" class="frac-palete-altura" min="0.1" step="0.01" value="100" required></div>
    </div>
    <div class="field">
      <div class="idx">×</div>
      <div><label>Qtde</label><input type="number" class="frac-palete-quantidade" min="1" step="1" value="1" title="Quantidade de paletes idênticos com essas mesmas dimensões" required></div>
    </div>
    <button type="button" class="btn-icone excluir frac-btn-remove-palete" title="Remover este palete">&times;</button>
  `;
  wrap.appendChild(row);
  row.querySelector('.frac-btn-remove-palete').addEventListener('click', () => { row.remove(); fracAtualizarCubagem(); });
  row.querySelectorAll('input').forEach(inp => inp.addEventListener('input', fracAtualizarCubagem));
}
document.getElementById('frac-btn-add-palete').addEventListener('click', fracCriarLinhaPalete);

function fracAtualizarCubagem(){
  const info = document.getElementById('frac-cubagem-info');
  const peso = pesoParaNumero(document.getElementById('frac-peso').value) || 0;
  const paletes = fracColetarPaletes().filter(p => p.comprimento > 0 && p.largura > 0 && p.altura > 0);
  const nomeTransporte = document.getElementById('frac-transporte').value;
  // Reaproveita transportesCache do formulário principal (já carregado
  // em inicializarFormulario, que roda sempre no load da página) -- sem
  // isso teria que buscar /parametros/transportes de novo aqui.
  const transp = transportesCache.find(t => t.nome === nomeTransporte);
  if(!transp || !transp.fator_cubagem || paletes.length === 0){ info.textContent = ''; return; }
  const volumeCm3Total = paletes.reduce((soma, p) => soma + (p.comprimento * p.largura * p.altura * p.quantidade), 0);
  const volumeM3Total = volumeCm3Total / 1000000;
  const pesoCubado = volumeM3Total * transp.fator_cubagem;
  const pesoConsiderado = Math.max(peso, pesoCubado);
  const qualPesa = pesoCubado > peso ? 'cubado' : 'real';
  const totalPaletes = paletes.reduce((soma, p) => soma + p.quantidade, 0);
  info.className = 'cep-info ok';
  info.textContent =
    `Volume total: ${volumeM3Total.toFixed(3)} m³ (${totalPaletes} palete${totalPaletes > 1 ? 's' : ''}) — ` +
    `Cubagem: ${pesoCubado.toFixed(2)} kg (fator ${transp.fator_cubagem} do transporte "${transp.nome}") — ` +
    `peso considerado no cálculo: ${pesoConsiderado.toFixed(2)} kg (peso ${qualPesa}).`;
}
['frac-peso', 'frac-comprimento', 'frac-largura', 'frac-altura', 'frac-quantidade'].forEach(id => {
  document.getElementById(id).addEventListener('input', fracAtualizarCubagem);
});
document.getElementById('frac-transporte').addEventListener('change', fracAtualizarCubagem);

async function fracInicializarFormulario(){
  if(fracInicializado) return;
  const btn = document.getElementById('frac-btn-calc');
  const errorBoxFrac = document.getElementById('frac-error-box');
  btn.disabled = true;
  btn.textContent = 'Carregando...';
  try{
    await Promise.all([
      carregarOpcoes('categorias', document.getElementById('frac-categoria')),
      carregarOpcoes('transportes', document.getElementById('frac-transporte')),
      carregarOpcoes('slas', document.getElementById('frac-sla')),
      carregarOpcoes('veiculos', document.getElementById('frac-veiculo')),
    ]);
    // filiaisCache já foi carregado pelo formulário principal (ver
    // carregarFiliais em inicializarFormulario) -- só preenche os
    // seletores daqui com o que já está em memória.
    preencherOpcoes(document.getElementById('frac-origem-filial'), filiaisCache);
    preencherOpcoes(document.getElementById('frac-destino-filial'), filiaisCache);
    // taxasCustomizaveisCache também já foi carregado pelo formulário
    // principal (ver carregarTaxasCustomizaveis em inicializarFormulario).
    preencherCamposTaxasCustomizaveis('frac-gris_pct', 'frac-ad_valorem_pct');
    atualizarLucrosTaxasCustomizaveis('frac-');
    const categoriaSel = document.getElementById('frac-categoria');
    if([...categoriaSel.options].some(o => o.value === 'Geral')) categoriaSel.value = 'Geral';
    fracAtualizarCubagem();
    fracInicializado = true;
  }catch(e){
    errorBoxFrac.textContent = 'Não foi possível carregar os parâmetros. Verifique se a API está ativa.';
    errorBoxFrac.classList.add('show');
  }finally{
    btn.disabled = false;
    btn.textContent = 'Calcular frete';
  }
}

const fracBtnGeo = document.getElementById('frac-btn-geo');
const fracGeoStatus = document.getElementById('frac-geo-status');
const fracDistanciaInput = document.getElementById('frac-distancia');
const fracPedagioInput = document.getElementById('frac-pedagio');
const fracCampoPedagio = document.getElementById('frac-campo-pedagio');

function fracInvalidarRotaCalculada(){
  fracRotaValida = false;
  fracCidadeOrigemResolvida = '';
  fracCidadeDestinoResolvida = '';
  fracPrioridadeRotaResolvida = '';
  fracGeoStatus.className = 'geo-status';
  fracGeoStatus.textContent = '';
}
document.getElementById('frac-origem-filial').addEventListener('change', fracInvalidarRotaCalculada);
document.getElementById('frac-destino-filial').addEventListener('change', fracInvalidarRotaCalculada);
document.getElementById('frac-veiculo').addEventListener('change', fracInvalidarRotaCalculada);

async function fracCalcularDistancia(){
  fracGeoStatus.className = 'geo-status';
  fracGeoStatus.textContent = '';
  fracRotaValida = false;
  fracCidadeOrigemResolvida = '';
  fracCidadeDestinoResolvida = '';
  fracPrioridadeRotaResolvida = '';

  fracBtnGeo.disabled = true;
  fracBtnGeo.textContent = 'Calculando...';
  fracGeoStatus.textContent = 'Consultando endereços...';

  try{
    const origemFilial = document.getElementById('frac-origem-filial').value;
    const destinoFilial = document.getElementById('frac-destino-filial').value;
    const veiculo = document.getElementById('frac-veiculo').value;
    const origemEndereco = enderecoDaFilial(origemFilial);
    const destinoEndereco = enderecoDaFilial(destinoFilial);
    fracCidadeOrigemResolvida = origemFilial;
    fracCidadeDestinoResolvida = destinoFilial;

    const res = await fetch(`${API_BASE}/geo/distancia`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      // veiculo aqui já vem do seletor (referência escolhida direto pela
      // pessoa) -- tem prioridade sobre a inferência por peso no backend
      // (ver DistanciaRequest.veiculo em schemas.py).
      body: JSON.stringify({origem: origemEndereco, destino: destinoEndereco, veiculo}),
    });
    const data = await res.json();
    if(!res.ok) throw new Error(data.detail || 'Não foi possível calcular a distância.');

    fracDistanciaInput.value = data.distancia_km;
    fracPrioridadeRotaResolvida = data.prioridade_rota || '';
    const horas = Math.floor(data.duracao_min / 60);
    const minutos = Math.round(data.duracao_min % 60);
    const tempoTexto = horas > 0 ? `${horas}h${minutos.toString().padStart(2,'0')}` : `${minutos} min`;

    let mensagemPedagio = '';
    if(typeof data.pedagio_valor === 'number'){
      fracPedagioInput.value = formatarValorMoeda(data.pedagio_valor);
      fracCampoPedagio.style.display = '';
      mensagemPedagio = (data.pedagio_pracas && data.pedagio_pracas.length)
        ? ` Pedágio: ${fmtBRL(data.pedagio_valor)} (${data.pedagio_pracas.join(', ')}).`
        : ` Pedágio estimado: ${fmtBRL(data.pedagio_valor)}.`;
    }else{
      fracCampoPedagio.style.display = 'none';
      fracPedagioInput.value = formatarValorMoeda(0);
    }

    const mensagemPrioridade = data.prioridade_rota ? ` Rota via ${data.prioridade_rota} (prioridade de rota).` : '';
    fracGeoStatus.classList.add('ok');
    fracGeoStatus.textContent = `Distância: ${data.distancia_km} km (≈ ${tempoTexto}).${mensagemPrioridade}${mensagemPedagio}`;
    fracRotaValida = true;
    return true;
  }catch(err){
    fracGeoStatus.classList.add('err');
    fracGeoStatus.textContent = err.message;
    return false;
  }finally{
    fracBtnGeo.disabled = false;
    fracBtnGeo.textContent = 'Calcular distância';
  }
}
fracBtnGeo.addEventListener('click', () => { fracCalcularDistancia(); });

document.getElementById('frac-toggle-servico').addEventListener('click', () => {
  const bloco = document.getElementById('frac-bloco-servico');
  const icon = document.getElementById('frac-icon-servico');
  const abrindo = bloco.style.display === 'none';
  bloco.style.display = abrindo ? '' : 'none';
  icon.classList.toggle('ti-chevron-right', !abrindo);
  icon.classList.toggle('ti-chevron-down', abrindo);
});

function fracIdValorCustoExtra(categoria){
  return `frac-custo-extra-valor-${categoria.replace(/\s+/g, '-')}`;
}
document.getElementById('frac-custos-extras-categorias').addEventListener('click', (ev) => {
  const btn = ev.target.closest('.seg-btn');
  if(!btn) return;
  const categoria = btn.dataset.categoria;
  const ativo = btn.classList.toggle('active');
  const linhaId = fracIdValorCustoExtra(categoria);
  if(ativo){
    const div = document.createElement('div');
    div.className = 'field';
    div.id = linhaId;
    div.innerHTML = `
      <div class="idx">·</div>
      <div>
        <label>${esc(categoria)} (R$)</label>
        <input type="text" inputmode="decimal" value="0,00" oninput="formatarMoedaDigitando(this)">
      </div>
    `;
    document.getElementById('frac-lista-valores-custos-extras').appendChild(div);
  }else{
    document.getElementById(linhaId)?.remove();
  }
});
function fracColetarCustosExtras(){
  return [...document.querySelectorAll('#frac-custos-extras-categorias .seg-btn.active')].map(btn => {
    const categoria = btn.dataset.categoria;
    const input = document.getElementById(fracIdValorCustoExtra(categoria))?.querySelector('input');
    return {categoria, valor: valorMoedaParaNumero(input ? input.value : '0')};
  });
}

document.getElementById('frac-btn-toggle-memoria').addEventListener('click', () => {
  const bloco = document.getElementById('frac-bloco-memoria-calculo');
  const label = document.getElementById('frac-btn-toggle-memoria-label');
  const abrindo = bloco.style.display === 'none';
  bloco.style.display = abrindo ? '' : 'none';
  label.textContent = abrindo ? 'Esconder detalhes das variáveis de cálculo' : 'Ver detalhes das variáveis de cálculo';
});

document.getElementById('frac-form-frete').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const errorBoxFrac = document.getElementById('frac-error-box');
  const btnFrac = document.getElementById('frac-btn-calc');
  const statusTagFrac = document.getElementById('frac-status-tag');
  errorBoxFrac.classList.remove('show');
  errorBoxFrac.textContent = '';
  document.getElementById('frac-stamp').classList.remove('show');
  fracUltimoOrcamento = null;
  document.getElementById('frac-historico-salvar-status').textContent = '';

  if(!fracRotaValida){
    const ok = await fracCalcularDistancia();
    if(!ok){
      errorBoxFrac.textContent = 'Não foi possível calcular a distância automaticamente. Confira as filiais escolhidas e clique em "Calcular frete" de novo.';
      errorBoxFrac.classList.add('show');
      return;
    }
  }

  const paletes = fracColetarPaletes();
  if(paletes.some(p => p.comprimento <= 0 || p.largura <= 0 || p.altura <= 0)){
    errorBoxFrac.textContent = 'Preencha comprimento, largura e altura de todos os paletes.';
    errorBoxFrac.classList.add('show');
    return;
  }

  const payload = {
    peso: pesoParaNumero(document.getElementById('frac-peso').value),
    paletes,
    distancia: parseFloat(fracDistanciaInput.value),
    pedagio: valorMoedaParaNumero(fracPedagioInput.value),
    cidade_origem: fracCidadeOrigemResolvida,
    cidade_destino: fracCidadeDestinoResolvida,
    prioridade_rota: fracPrioridadeRotaResolvida,
    valor_mercadoria: valorMoedaParaNumero(document.getElementById('frac-valor_mercadoria').value),
    categoria: document.getElementById('frac-categoria').value,
    transporte: document.getElementById('frac-transporte').value,
    sla: document.getElementById('frac-sla').value,
    veiculo: document.getElementById('frac-veiculo').value,
    custos_extras: fracColetarCustosExtras(),
    gris_pct: parseFloat(document.getElementById('frac-gris_pct').value),
    ad_valorem_pct: parseFloat(document.getElementById('frac-ad_valorem_pct').value),
  };

  btnFrac.disabled = true;
  btnFrac.textContent = 'Calculando...';
  statusTagFrac.textContent = 'Processando';

  try{
    const res = await fetch(`${API_BASE}/orcamento/fracionado`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if(!res.ok) throw new Error(data.detail || 'Não foi possível calcular o frete.');

    const calc = data.calculos_intermediarios;
    const result = data.resultado;
    renderizarMemoriaCalculo(data, 'frac-bloco-memoria-calculo');

    document.getElementById('frac-out-total').textContent = fmtBRL(result.frete_total);
    document.getElementById('frac-out-veiculo').textContent = data.entrada.veiculo;
    document.getElementById('frac-out-prazo').textContent = `${result.prazo_estimado_dias_uteis} dias úteis`;

    const fmtFaixaAte = (ate) => (ate >= 999999 ? '∞' : ate);
    document.getElementById('frac-d-peso').textContent = `${calc.peso_considerado_kg} kg`;
    document.getElementById('frac-d-faixa-peso').textContent =
      `${calc.faixa_peso_de}–${fmtFaixaAte(calc.faixa_peso_ate)} kg (base ${fmtBRL(calc.tarifa_base_peso)} + ${fmtBRL(calc.custo_kg_adicional_peso)}/kg acima de ${calc.faixa_peso_de}kg)`;
    document.getElementById('frac-d-custo-peso').textContent = fmtBRL(calc.custo_base_peso);
    document.getElementById('frac-d-km').textContent = `${calc.distancia_faturavel_km} km`;
    document.getElementById('frac-d-faixa-distancia').textContent =
      `${calc.faixa_distancia_de}–${fmtFaixaAte(calc.faixa_distancia_ate)} km (fixa ${fmtBRL(calc.taxa_fixa_distancia)} + ${fmtBRL(calc.tarifa_km_distancia)}/km)`;
    document.getElementById('frac-d-custo-distancia').textContent = fmtBRL(calc.custo_base_distancia);
    document.getElementById('frac-d-base').textContent = fmtBRL(calc.frete_base);
    document.getElementById('frac-d-ajustado').textContent = fmtBRL(calc.frete_ajustado);

    const linhaPedagio = document.getElementById('frac-linha-pedagio');
    if(calc.pedagio > 0){
      linhaPedagio.querySelector('span').textContent = calc.pedagio_estimado_pct
        ? `Pedágio (estimado, ${calc.pedagio_estimado_pct}% do frete)` : 'Pedágio';
      document.getElementById('frac-d-pedagio').textContent = fmtBRL(calc.pedagio);
      linhaPedagio.style.display = 'flex';
    }else{ linhaPedagio.style.display = 'none'; }

    const linhaTaxasRegionais = document.getElementById('frac-linha-taxas-regionais');
    if(calc.custo_taxas_regionais > 0){
      document.getElementById('frac-d-taxas-regionais').textContent = fmtBRL(calc.custo_taxas_regionais);
      linhaTaxasRegionais.style.display = 'flex';
    }else{ linhaTaxasRegionais.style.display = 'none'; }

    const linhaTaxaBalsa = document.getElementById('frac-linha-taxa-balsa');
    if(calc.custo_balsa > 0 && calc.taxa_balsa){
      document.getElementById('frac-d-taxa-balsa').textContent = fmtBRL(calc.custo_balsa);
      linhaTaxaBalsa.title = `${calc.taxa_balsa.cidade_origem} → ${calc.taxa_balsa.cidade_destino} (${calc.taxa_balsa.veiculo})`;
      linhaTaxaBalsa.style.display = 'flex';
    }else{ linhaTaxaBalsa.style.display = 'none'; }

    const taxasAdicionaisLista = calc.taxas_adicionais || [];
    const taxaGris = taxasAdicionaisLista.find(t => t.nome.trim().toLowerCase() === 'gris');
    const taxaAdValorem = taxasAdicionaisLista.find(t => t.nome.trim().toLowerCase() === 'ad valorem');
    const outrasTaxasAdicionais = taxasAdicionaisLista.filter(t => {
      const chave = t.nome.trim().toLowerCase();
      return chave !== 'gris' && chave !== 'ad valorem';
    });

    const linhaGris = document.getElementById('frac-linha-gris');
    if(taxaGris && taxaGris.valor_aplicado > 0){
      document.getElementById('frac-d-gris').textContent = `${fmtBRL(taxaGris.valor_aplicado)} (${taxaGris.valor_configurado}%)`;
      linhaGris.style.display = 'flex';
    }else{ linhaGris.style.display = 'none'; }

    const linhaAdValorem = document.getElementById('frac-linha-ad-valorem');
    if(taxaAdValorem && taxaAdValorem.valor_aplicado > 0){
      document.getElementById('frac-d-ad-valorem').textContent = `${fmtBRL(taxaAdValorem.valor_aplicado)} (${taxaAdValorem.valor_configurado}%)`;
      linhaAdValorem.style.display = 'flex';
    }else{ linhaAdValorem.style.display = 'none'; }

    const custoOutrasTaxasAdicionais = outrasTaxasAdicionais.reduce((soma, t) => soma + t.valor_aplicado, 0);
    const linhaTaxas = document.getElementById('frac-linha-taxas');
    const blocoDetalheTaxas = document.getElementById('frac-bloco-detalhe-taxas');
    if(custoOutrasTaxasAdicionais > 0){
      document.getElementById('frac-d-taxas').textContent = fmtBRL(custoOutrasTaxasAdicionais);
      linhaTaxas.style.display = 'flex';
      document.getElementById('frac-lista-detalhe-taxas').innerHTML = outrasTaxasAdicionais.map(t => {
        const rotulo = t.tipo === 'percentual' ? `${esc(t.nome)} (${t.valor_configurado}%)` : esc(t.nome);
        return `<div class="line"><span>${rotulo}</span><span>${fmtBRL(t.valor_aplicado)}</span></div>`;
      }).join('');
      blocoDetalheTaxas.style.display = 'block';
    }else{
      linhaTaxas.style.display = 'none';
      blocoDetalheTaxas.style.display = 'none';
    }

    const linhaCustosExtras = document.getElementById('frac-linha-custos-extras');
    const blocoDetalheCustosExtras = document.getElementById('frac-bloco-detalhe-custos-extras');
    if(calc.custo_extra_total > 0){
      document.getElementById('frac-d-custos-extras').textContent = fmtBRL(calc.custo_extra_total);
      linhaCustosExtras.style.display = 'flex';
      document.getElementById('frac-lista-detalhe-custos-extras').innerHTML = (calc.custos_extras || []).map(c =>
        `<div class="line"><span>${esc(c.categoria)}</span><span>${fmtBRL(c.valor_aplicado)}</span></div>`
      ).join('');
      blocoDetalheCustosExtras.style.display = 'block';
    }else{
      linhaCustosExtras.style.display = 'none';
      blocoDetalheCustosExtras.style.display = 'none';
    }

    const linhaMargemLucro = document.getElementById('frac-linha-margem-lucro');
    if(calc.valor_margem_lucro > 0){
      document.getElementById('frac-d-margem-lucro').textContent = `${fmtBRL(calc.valor_margem_lucro)} (${calc.margem_lucro_pct}%)`;
      linhaMargemLucro.style.display = 'flex';
    }else{ linhaMargemLucro.style.display = 'none'; }

    const linhaAjustePiso = document.getElementById('frac-linha-ajuste-piso');
    if(calc.ajuste_piso_markup > 0){
      document.getElementById('frac-d-ajuste-piso').textContent = fmtBRL(calc.ajuste_piso_markup);
      linhaAjustePiso.style.display = 'flex';
    }else{ linhaAjustePiso.style.display = 'none'; }

    const linhaPisCofins = document.getElementById('frac-linha-pis-cofins');
    if(calc.valor_pis_cofins > 0){
      document.getElementById('frac-d-pis-cofins').textContent = fmtBRL(calc.valor_pis_cofins);
      linhaPisCofins.title = `${calc.aliquota_pis_cofins_pct}%, aplicado por dentro sobre ${fmtBRL(calc.frete_sem_pis_cofins)}`;
      linhaPisCofins.style.display = 'flex';
    }else{ linhaPisCofins.style.display = 'none'; }

    const linhaIcms = document.getElementById('frac-linha-icms');
    if(calc.valor_icms > 0){
      document.getElementById('frac-d-icms').textContent = fmtBRL(calc.valor_icms);
      linhaIcms.title = `${calc.uf_origem_icms} → ${calc.uf_destino_icms} (${calc.aliquota_icms_pct}% somado por fora sobre ${fmtBRL(calc.frete_sem_icms)}, já com a margem de lucro embutida)`;
      linhaIcms.style.display = 'flex';
    }else{ linhaIcms.style.display = 'none'; }

    document.getElementById('frac-d-total-operacao').textContent = fmtBRL(calc.total_custo_operacao);
    document.getElementById('frac-d-total-impostos-taxas').textContent = fmtBRL(calc.total_impostos_taxas);
    document.getElementById('frac-d-operacao-mais-impostos').textContent = fmtBRL(calc.frete_sem_pis_cofins);
    document.getElementById('frac-d-total-antes-icms').textContent = fmtBRL(calc.frete_sem_icms);

    document.getElementById('frac-d-total').textContent = fmtBRL(result.frete_total);

    document.getElementById('frac-result-empty').style.display = 'none';
    document.getElementById('frac-result-content').style.display = 'block';
    requestAnimationFrame(() => document.getElementById('frac-stamp').classList.add('show'));
    statusTagFrac.textContent = 'Calculado';

    fracUltimoOrcamento = {payload, resultado: data};
  }catch(err){
    errorBoxFrac.textContent = err.message;
    errorBoxFrac.classList.add('show');
    statusTagFrac.textContent = 'Erro';
  }finally{
    btnFrac.disabled = false;
    btnFrac.textContent = 'Calcular frete';
  }
});

document.getElementById('frac-btn-salvar-historico').addEventListener('click', async () => {
  const statusEl = document.getElementById('frac-historico-salvar-status');
  const cliente = document.getElementById('frac-hist-cliente').value.trim();
  const responsavel = document.getElementById('frac-hist-responsavel').value.trim();

  if(!fracUltimoOrcamento){
    statusEl.style.color = 'var(--err)';
    statusEl.textContent = 'Calcule um orçamento antes de salvar.';
    return;
  }
  if(!currentUser){
    statusEl.style.color = 'var(--err)';
    statusEl.textContent = 'Faça login para salvar no histórico (menu "Entrar").';
    return;
  }
  if(!cliente || !responsavel){
    statusEl.style.color = 'var(--err)';
    statusEl.textContent = 'Preencha Cliente e Responsável (lá no topo do formulário) antes de salvar.';
    return;
  }

  const btnSalvar = document.getElementById('frac-btn-salvar-historico');
  btnSalvar.disabled = true;
  statusEl.style.color = 'var(--text-dim)';
  statusEl.textContent = 'Salvando...';

  try{
    const {payload, resultado} = fracUltimoOrcamento;
    const res = await fetch(`${API_BASE}/historico`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        cliente, responsavel,
        origem_resumo: document.getElementById('frac-origem-filial').value,
        destino_resumo: document.getElementById('frac-destino-filial').value,
        veiculo: resultado.entrada.veiculo,
        distancia_km: resultado.entrada.distancia_km,
        valor_mercadoria: resultado.entrada.valor_mercadoria,
        frete_total: resultado.resultado.frete_total,
        dados: {payload, resultado},
      }),
    });
    const data = await res.json();
    if(!res.ok) throw new Error(data.detail || 'Erro ao salvar no histórico.');

    statusEl.style.color = 'var(--ok)';
    statusEl.textContent = `Salvo como ${data.codigo}.`;
  }catch(e){
    statusEl.style.color = 'var(--err)';
    statusEl.textContent = e.message;
  }finally{
    btnSalvar.disabled = false;
  }
});

// Seções recolhíveis da Tabela de Preços (Cadastros Gerais, Veículos e
// Tarifas, Coleta e Entrega, Rotas, Pedágio, Taxas e Impostos) --
// diferente de Serviço/Custos Extras no formulário de orçamento, aqui
// começam abertas (a pessoa vem pra essa tela justamente pra editar
// alguma tabela, não faz sentido esconder tudo de cara).
document.querySelectorAll('.precos-section-toggle').forEach(header => {
  header.addEventListener('click', () => {
    const bloco = document.getElementById(header.dataset.target);
    const icon = header.querySelector('.precos-section-icon');
    const abrindo = bloco.style.display === 'none';
    bloco.style.display = abrindo ? '' : 'none';
    icon.classList.toggle('ti-chevron-down', abrindo);
    icon.classList.toggle('ti-chevron-right', !abrindo);
  });
});

document.getElementById('btn-toggle-memoria').addEventListener('click', () => {
  const bloco = document.getElementById('bloco-memoria-calculo');
  const label = document.getElementById('btn-toggle-memoria-label');
  const abrindo = bloco.style.display === 'none';
  bloco.style.display = abrindo ? '' : 'none';
  label.textContent = abrindo ? 'Esconder detalhes das variáveis de cálculo' : 'Ver detalhes das variáveis de cálculo';
});

document.getElementById('btn-salvar-historico').addEventListener('click', async () => {
  const statusEl = document.getElementById('historico-salvar-status');
  const cliente = document.getElementById('hist-cliente').value.trim();
  const responsavel = document.getElementById('hist-responsavel').value.trim();

  if(!ultimoOrcamento){
    statusEl.style.color = 'var(--err)';
    statusEl.textContent = 'Calcule um orçamento antes de salvar.';
    return;
  }
  if(!currentUser){
    statusEl.style.color = 'var(--err)';
    statusEl.textContent = 'Faça login para salvar no histórico (menu "Entrar").';
    return;
  }
  if(!cliente || !responsavel){
    statusEl.style.color = 'var(--err)';
    statusEl.textContent = 'Preencha Cliente e Responsável (lá no topo do formulário) antes de salvar.';
    return;
  }

  const btnSalvar = document.getElementById('btn-salvar-historico');
  btnSalvar.disabled = true;
  statusEl.style.color = 'var(--text-dim)';
  statusEl.textContent = 'Salvando...';

  try{
    const {payload, resultado} = ultimoOrcamento;
    const origemResumo = origemTipo === 'filial' ? origemFilialSel.value : (cidadeOrigemResolvida || 'Retirada no cliente');
    const destinoResumo = destinoTipo === 'filial' ? destinoFilialSel.value : (cidadeDestinoResolvida || 'Entrega no cliente');

    const res = await fetch(`${API_BASE}/historico`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        cliente, responsavel,
        origem_resumo: origemResumo,
        destino_resumo: destinoResumo,
        veiculo: resultado.entrada.veiculo,
        distancia_km: resultado.entrada.distancia_km,
        valor_mercadoria: resultado.entrada.valor_mercadoria,
        frete_total: resultado.resultado.frete_total,
        dados: {payload, resultado},
      }),
    });
    const data = await res.json();
    if(!res.ok) throw new Error(data.detail || 'Erro ao salvar no histórico.');

    statusEl.style.color = 'var(--ok)';
    statusEl.textContent = `Salvo como ${data.codigo}.`;
  }catch(e){
    statusEl.style.color = 'var(--err)';
    statusEl.textContent = e.message;
  }finally{
    btnSalvar.disabled = false;
  }
});

// ============================================================
// Navegação entre views (Cotação Lotação / Tabela de Preços / etc.)
// ============================================================

const views = {
  orcamento: document.getElementById('view-orcamento'),
  'orcamento-fracionado': document.getElementById('view-orcamento-fracionado'),
  precos: document.getElementById('view-precos'),
  historico: document.getElementById('view-historico'),
  config: document.getElementById('view-config'),
  login: document.getElementById('view-login'),
};

function mostrarView(viewName){
  const link = document.querySelector(`.sidebar-nav a[data-view="${viewName}"]`);
  document.querySelectorAll('.sidebar-nav a').forEach(a => a.classList.remove('active'));
  if(link) link.classList.add('active');

  Object.values(views).forEach(v => { if(v) v.style.display = 'none'; });
  document.getElementById('view-historico-detalhe').style.display = 'none';
  views[viewName].style.display = 'block';

  if(viewName === 'orcamento-fracionado') fracInicializarFormulario();
  if(viewName === 'precos') carregarTabelaPrecos();
  if(viewName === 'historico') carregarHistorico();
  if(viewName === 'config'){ carregarConfiguracoes(); carregarBancoDadosConfig(); }
}

document.querySelectorAll('.sidebar-nav a').forEach(link => {
  link.addEventListener('click', (ev) => {
    ev.preventDefault();
    const viewName = link.dataset.view;
    if(!viewName || !views[viewName]) return;

    if(link.hasAttribute('data-requer-login') && !currentUser){
      mostrarView('login');
      return;
    }
    if(link.hasAttribute('data-requer-admin') && (!currentUser || currentUser.role !== 'admin')){
      mostrarView('login');
      return;
    }
    mostrarView(viewName);
  });
});

// ============================================================
// Autenticação — sessão, login/logout, troca de senha e
// visibilidade dos itens do menu conforme o papel do usuário
// ============================================================

let currentUser = null;

function atualizarUIAuth(){
  const logado = !!currentUser;
  const admin = logado && currentUser.role === 'admin';

  document.querySelectorAll('.sidebar-nav a[data-requer-login]').forEach(a => a.classList.toggle('hidden', !logado));
  document.querySelectorAll('.sidebar-nav a[data-requer-admin]').forEach(a => a.classList.toggle('hidden', !admin));
  document.getElementById('nav-login').classList.toggle('hidden', logado);

  document.getElementById('sidebar-user').classList.toggle('hidden', !logado);
  if(logado){
    document.getElementById('sidebar-user-nome').textContent = currentUser.nome;
    document.getElementById('sidebar-user-role').textContent = currentUser.role === 'admin' ? 'Administrador' : 'Usuário';
  }

  // Login com a senha padrão (ex: admin recém-criado) — abre a troca de
  // senha já aberta e avisada, pra não passar despercebido.
  if(logado && currentUser.deve_trocar_senha){
    document.getElementById('senha-form').classList.remove('hidden');
    const statusEl = document.getElementById('senha-status');
    statusEl.className = 'senha-status err';
    statusEl.textContent = 'Você está com a senha padrão — troque agora antes de continuar.';
  }

  // Se a view atual exigia login/admin e o usuário deixou de ter acesso
  // (ex: fez logout com "Histórico" aberto), volta pra Cotação Lotação.
  const viewAtual = Object.entries(views).find(([, el]) => el && el.style.display !== 'none');
  if(viewAtual){
    const [nomeView] = viewAtual;
    const link = document.querySelector(`.sidebar-nav a[data-view="${nomeView}"]`);
    if(link && link.classList.contains('hidden')){
      mostrarView('orcamento');
    }
  }
}

async function verificarSessao(){
  try{
    const res = await fetch(`${API_BASE}/auth/me`);
    currentUser = res.ok ? await res.json() : null;
  }catch{
    currentUser = null;
  }
  atualizarUIAuth();
}

document.getElementById('form-login').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const errorBoxLogin = document.getElementById('login-error');
  const btnLogin = document.getElementById('btn-login');
  errorBoxLogin.classList.remove('show');
  btnLogin.disabled = true;
  btnLogin.textContent = 'Entrando...';
  try{
    const res = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        username: document.getElementById('login-username').value.trim(),
        senha: document.getElementById('login-senha').value,
      }),
    });
    const data = await res.json();
    if(!res.ok) throw new Error(data.detail || 'Não foi possível entrar.');
    currentUser = data;
    atualizarUIAuth();
    document.getElementById('login-username').value = '';
    document.getElementById('login-senha').value = '';
    mostrarView(currentUser.role === 'admin' ? 'config' : 'historico');
  }catch(e){
    errorBoxLogin.textContent = e.message;
    errorBoxLogin.classList.add('show');
  }finally{
    btnLogin.disabled = false;
    btnLogin.textContent = 'Entrar';
  }
});

document.getElementById('btn-logout').addEventListener('click', async () => {
  try{ await fetch(`${API_BASE}/auth/logout`, {method: 'POST'}); }catch{}
  currentUser = null;
  document.getElementById('senha-form').classList.add('hidden');
  atualizarUIAuth();
  mostrarView('orcamento');
});

document.getElementById('btn-trocar-senha').addEventListener('click', () => {
  document.getElementById('senha-form').classList.toggle('hidden');
});

document.getElementById('btn-confirmar-senha').addEventListener('click', async () => {
  const senhaAtualEl = document.getElementById('ts-senha-atual');
  const senhaNovaEl = document.getElementById('ts-senha-nova');
  const statusEl = document.getElementById('senha-status');
  statusEl.className = 'senha-status';
  try{
    const res = await fetch(`${API_BASE}/auth/trocar-senha`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({senha_atual: senhaAtualEl.value, senha_nova: senhaNovaEl.value}),
    });
    const data = await res.json();
    if(!res.ok) throw new Error(data.detail || 'Erro ao trocar a senha.');
    if(currentUser) currentUser.deve_trocar_senha = false;
    statusEl.className = 'senha-status ok';
    statusEl.textContent = 'Senha alterada.';
    senhaAtualEl.value = '';
    senhaNovaEl.value = '';
  }catch(e){
    statusEl.className = 'senha-status err';
    statusEl.textContent = e.message;
  }
});

// ============================================================
// Configurações — status do sistema e ações administrativas
// ============================================================

async function carregarConfiguracoes(){
  carregarUsuarios();
  const statusTag = document.getElementById('config-status-tag');
  const apiStatusEl = document.getElementById('config-api-status');
  const versaoEl = document.getElementById('config-versao');
  const geoEl = document.getElementById('config-geo-provider');
  const dbEl = document.getElementById('config-db-path');

  statusTag.textContent = '…';
  apiStatusEl.textContent = 'Verificando...';

  try{
    const res = await fetch(`${API_BASE}/api/status`);
    if(!res.ok) throw new Error();
    const data = await res.json();
    statusTag.textContent = 'Online';
    apiStatusEl.textContent = 'Online';
    versaoEl.textContent = data.versao || '-';
    geoEl.textContent = data.geo_provider === 'google'
      ? 'Google Maps (chave configurada)'
      : 'OpenStreetMap — Nominatim + OSRM (gratuito)';
    dbEl.textContent = data.banco || '-';
  }catch(err){
    statusTag.textContent = 'Offline';
    apiStatusEl.textContent = 'Não foi possível conectar à API.';
    versaoEl.textContent = '-';
    geoEl.textContent = '-';
    dbEl.textContent = '-';
  }
}

const TIPOS_BANCO_LABEL = {
  sqlite: 'SQLite (arquivo local)', sqlserver: 'SQL Server', mysql: 'MySQL', postgresql: 'PostgreSQL',
};

function _bdAtualizarCamposVisiveis(){
  const tipo = document.getElementById('bd-tipo').value;
  document.getElementById('bd-campo-sqlite_path').style.display = tipo === 'sqlite' ? '' : 'none';
  document.getElementById('bd-campos-servidor').style.display = tipo === 'sqlite' ? 'none' : '';
}

function _bdLerFormulario(){
  return {
    tipo: document.getElementById('bd-tipo').value,
    sqlite_path: document.getElementById('bd-sqlite_path').value,
    host: document.getElementById('bd-host').value,
    porta: parseInt(document.getElementById('bd-porta').value, 10) || 0,
    banco: document.getElementById('bd-banco').value,
    usuario: document.getElementById('bd-usuario').value,
    senha: document.getElementById('bd-senha').value,
  };
}

async function carregarBancoDadosConfig(){
  const tipoSel = document.getElementById('bd-tipo');
  const tagEl = document.getElementById('bd-tipo-atual-tag');
  if(!tipoSel.dataset.wired){
    tipoSel.addEventListener('change', _bdAtualizarCamposVisiveis);
    tipoSel.dataset.wired = '1';
  }
  try{
    const res = await fetch(`${API_BASE}/admin/banco-dados`);
    if(!res.ok) throw new Error();
    const cfg = await res.json();
    tagEl.textContent = TIPOS_BANCO_LABEL[cfg.tipo] || cfg.tipo;
    tipoSel.value = cfg.tipo;
    document.getElementById('bd-sqlite_path').value = cfg.sqlite_path || '';
    document.getElementById('bd-host').value = cfg.host || '';
    document.getElementById('bd-porta').value = cfg.porta || '';
    document.getElementById('bd-banco').value = cfg.banco || '';
    document.getElementById('bd-usuario').value = cfg.usuario || '';
    document.getElementById('bd-senha').value = '';
    document.getElementById('bd-senha').placeholder = cfg.senha_configurada ? '(mantida — digite pra trocar)' : '';
    _bdAtualizarCamposVisiveis();
  }catch(err){
    tagEl.textContent = 'erro';
  }
}

document.getElementById('btn-testar-banco').addEventListener('click', async () => {
  const btn = document.getElementById('btn-testar-banco');
  const statusEl = document.getElementById('banco-dados-status');
  btn.disabled = true;
  statusEl.className = 'geo-status';
  statusEl.textContent = 'Testando conexão...';
  try{
    const res = await fetch(`${API_BASE}/admin/banco-dados/testar`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(_bdLerFormulario()),
    });
    const data = await res.json();
    if(!res.ok) throw new Error(data.detail || 'Falha ao testar a conexão.');
    statusEl.classList.add('ok');
    statusEl.textContent = data.mensagem || 'Conexão bem-sucedida.';
  }catch(e){
    statusEl.classList.add('err');
    statusEl.textContent = e.message;
  }finally{
    btn.disabled = false;
  }
});

document.getElementById('btn-aplicar-banco').addEventListener('click', async () => {
  const dados = _bdLerFormulario();
  const confirmacao = confirm(
    `Isso vai criar o schema em "${TIPOS_BANCO_LABEL[dados.tipo] || dados.tipo}", copiar TODOS os dados ` +
    'do banco atual pra ele, e passar a usar esse banco novo a partir de agora. Confirma?'
  );
  if(!confirmacao) return;

  const btn = document.getElementById('btn-aplicar-banco');
  const statusEl = document.getElementById('banco-dados-status');
  btn.disabled = true;
  statusEl.className = 'geo-status';
  statusEl.textContent = 'Migrando dados — isso pode demorar um pouco...';
  try{
    const res = await fetch(`${API_BASE}/admin/banco-dados/aplicar`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(dados),
    });
    const data = await res.json();
    if(!res.ok) throw new Error(data.detail || 'Falha ao aplicar a mudança de banco.');
    const totalLinhas = Object.values(data.linhas_migradas || {}).reduce((a, b) => a + b, 0);
    statusEl.classList.add('ok');
    statusEl.textContent = `Banco trocado com sucesso — ${totalLinhas} linhas migradas.`;
    await carregarBancoDadosConfig();
    await carregarConfiguracoes();
  }catch(e){
    statusEl.classList.add('err');
    statusEl.textContent = e.message;
  }finally{
    btn.disabled = false;
  }
});

async function carregarUsuarios(){
  const container = document.getElementById('precos-usuarios');
  container.innerHTML = `
    <div class="card-head"><h2>Usuários</h2><span class="tag" id="precos-usuarios-count">…</span></div>
    <div class="tabela-wrap"><table class="tabela-editor">
      <thead><tr><th>Nome</th><th>Usuário</th><th>Papel</th><th>Ativo</th><th>Nova senha</th><th>Ações</th></tr></thead>
      <tbody></tbody>
    </table></div>
    <div class="precos-status"></div>
  `;
  const tbody = container.querySelector('tbody');
  const statusEl = container.querySelector('.precos-status');
  const countTag = document.getElementById('precos-usuarios-count');

  const mostrarStatus = (msg, ok) => mostrarStatusPrecos(statusEl, msg, ok);

  function criarSelect(opcoes, valorAtual){
    const sel = document.createElement('select');
    opcoes.forEach(([v, label]) => {
      const op = document.createElement('option');
      op.value = v; op.textContent = label;
      sel.appendChild(op);
    });
    sel.value = valorAtual;
    return sel;
  }

  let itens = [];
  try{
    const res = await fetch(`${API_BASE}/admin/usuarios`);
    if(!res.ok) throw new Error(`Erro HTTP ${res.status}`);
    itens = await res.json();
  }catch(e){
    mostrarStatus('Falha ao carregar usuários.', false);
    countTag.textContent = 'erro';
    return;
  }
  countTag.textContent = `${itens.length} usuário${itens.length === 1 ? '' : 's'}`;

  itens.forEach(item => {
    const tr = document.createElement('tr');

    const inputNome = document.createElement('input');
    inputNome.type = 'text'; inputNome.value = item.nome;

    const inputUsername = document.createElement('input');
    inputUsername.type = 'text'; inputUsername.value = item.username;

    const selRole = criarSelect([['admin', 'Administrador'], ['usuario', 'Usuário']], item.role);
    const selAtivo = criarSelect([['1', 'Sim'], ['0', 'Não']], item.ativo ? '1' : '0');

    const inputSenha = document.createElement('input');
    inputSenha.type = 'password'; inputSenha.placeholder = 'Deixe em branco p/ manter';
    inputSenha.autocomplete = 'new-password'; inputSenha.minLength = 8;

    [inputNome, inputUsername, selRole, selAtivo, inputSenha].forEach(el => {
      const td = document.createElement('td');
      td.appendChild(el);
      tr.appendChild(td);
    });

    const tdAcoes = document.createElement('td');
    tdAcoes.className = 'col-acoes';

    const btnSalvar = criarElemento('button', {type: 'button', class: 'btn-icone'}, '💾 Salvar');
    btnSalvar.addEventListener('click', async () => {
      try{
        const dados = {
          nome: inputNome.value, username: inputUsername.value,
          role: selRole.value, ativo: selAtivo.value === '1',
          senha: inputSenha.value,
        };
        const res = await fetch(`${API_BASE}/admin/usuarios/${item.id}`, {
          method: 'PUT',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(dados),
        });
        const data = await res.json();
        if(!res.ok) throw new Error(data.detail || 'Erro ao salvar.');
        inputSenha.value = '';
        mostrarStatus('Usuário salvo.', true);
        if(currentUser && item.id === currentUser.id){
          currentUser.nome = dados.nome;
          atualizarUIAuth();
        }
      }catch(e){ mostrarStatus(e.message, false); }
    });

    const btnExcluir = criarElemento('button', {type: 'button', class: 'btn-icone excluir'}, '🗑 Excluir');
    btnExcluir.addEventListener('click', async () => {
      if(!confirm(`Excluir o usuário "${item.username}"? Essa ação não pode ser desfeita.`)) return;
      try{
        const res = await fetch(`${API_BASE}/admin/usuarios/${item.id}`, {method: 'DELETE'});
        if(!res.ok){
          const data = await res.json();
          throw new Error(data.detail || 'Erro ao excluir.');
        }
        await carregarUsuarios();
        mostrarStatus('Usuário excluído.', true);
      }catch(e){ mostrarStatus(e.message, false); }
    });

    tdAcoes.appendChild(btnSalvar);
    tdAcoes.appendChild(btnExcluir);
    tr.appendChild(tdAcoes);
    tbody.appendChild(tr);
  });

  // Linha para adicionar um novo usuário
  const trNova = document.createElement('tr');
  trNova.className = 'linha-nova';

  const inputNomeNovo = document.createElement('input');
  inputNomeNovo.type = 'text'; inputNomeNovo.placeholder = 'Nome';

  const inputUsernameNovo = document.createElement('input');
  inputUsernameNovo.type = 'text'; inputUsernameNovo.placeholder = 'Usuário (login)';

  const selRoleNovo = criarSelect([['admin', 'Administrador'], ['usuario', 'Usuário']], 'usuario');
  const selAtivoNovo = criarSelect([['1', 'Sim'], ['0', 'Não']], '1');

  const inputSenhaNovo = document.createElement('input');
  inputSenhaNovo.type = 'password'; inputSenhaNovo.placeholder = 'Senha (mín. 8)';
  inputSenhaNovo.autocomplete = 'new-password'; inputSenhaNovo.minLength = 8;

  [inputNomeNovo, inputUsernameNovo, selRoleNovo, selAtivoNovo, inputSenhaNovo].forEach(el => {
    const td = document.createElement('td');
    td.appendChild(el);
    trNova.appendChild(td);
  });

  const tdAcoesNova = document.createElement('td');
  const btnAdd = criarElemento('button', {type: 'button', class: 'btn-icone'}, '+ Adicionar');
  btnAdd.addEventListener('click', async () => {
    try{
      const dados = {
        nome: inputNomeNovo.value, username: inputUsernameNovo.value,
        role: selRoleNovo.value, ativo: selAtivoNovo.value === '1',
        senha: inputSenhaNovo.value,
      };
      const res = await fetch(`${API_BASE}/admin/usuarios`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(dados),
      });
      const data = await res.json();
      if(!res.ok) throw new Error(data.detail || 'Erro ao adicionar.');
      await carregarUsuarios();
      mostrarStatus('Usuário adicionado.', true);
    }catch(e){ mostrarStatus(e.message, false); }
  });
  tdAcoesNova.appendChild(btnAdd);
  trNova.appendChild(tdAcoesNova);
  tbody.appendChild(trNova);
}

document.getElementById('btn-recarregar-parametros').addEventListener('click', async () => {
  const btn = document.getElementById('btn-recarregar-parametros');
  const statusEl = document.getElementById('config-reload-status');
  btn.disabled = true;
  statusEl.className = 'geo-status';
  statusEl.textContent = 'Recarregando...';
  try{
    const res = await fetch(`${API_BASE}/admin/reload`, {method: 'POST'});
    const data = await res.json();
    if(!res.ok) throw new Error(data.detail || 'Falha ao recarregar os parâmetros.');
    statusEl.className = 'geo-status ok';
    statusEl.textContent = data.mensagem || 'Parâmetros recarregados com sucesso.';
  }catch(err){
    statusEl.className = 'geo-status err';
    statusEl.textContent = err.message || 'Erro ao recarregar os parâmetros.';
  }finally{
    btn.disabled = false;
  }
});

const sidebarEl = document.getElementById('sidebar');
const btnCollapseSidebar = document.getElementById('btn-collapse-sidebar');
if(localStorage.getItem('sidebarRecolhida') === '1'){
  sidebarEl.classList.add('collapsed');
}
btnCollapseSidebar.addEventListener('click', () => {
  sidebarEl.classList.toggle('collapsed');
  localStorage.setItem('sidebarRecolhida', sidebarEl.classList.contains('collapsed') ? '1' : '0');
});

// Alternância de tema claro/escuro — o tema salvo já é aplicado antes do
// primeiro paint por um script no <head> (evita flash do tema errado).
const btnThemeToggle = document.getElementById('btn-theme-toggle');
const themeToggleIcon = document.getElementById('theme-toggle-icon');
const themeToggleLabel = document.getElementById('theme-toggle-label');
function aplicarTema(tema){
  if(tema === 'light'){
    document.documentElement.setAttribute('data-theme', 'light');
  }else{
    document.documentElement.removeAttribute('data-theme');
  }
  themeToggleIcon.className = tema === 'light' ? 'ti ti-moon' : 'ti ti-sun';
  themeToggleLabel.textContent = tema === 'light' ? 'Tema escuro' : 'Tema claro';
  const metaThemeColor = document.querySelector('meta[name="theme-color"]');
  if(metaThemeColor) metaThemeColor.setAttribute('content', tema === 'light' ? '#F4F7FA' : '#0A0F14');
}
aplicarTema(localStorage.getItem('frete_theme') === 'light' ? 'light' : 'dark');
btnThemeToggle.addEventListener('click', () => {
  const atual = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
  const proximo = atual === 'light' ? 'dark' : 'light';
  localStorage.setItem('frete_theme', proximo);
  aplicarTema(proximo);
});

// ============================================================
// Tabela de Preços — editor genérico (funciona pra qualquer
// tabela de preço: cria linha, edita, salva, exclui)
// ============================================================

// Mensagem de status (sucesso some sozinha em 3s, erro fica) usada tanto
// por carregarUsuarios quanto por criarEditorTabela -- cada um chama com
// o próprio elemento `.precos-status`.
function mostrarStatusPrecos(statusEl, msg, ok){
  statusEl.textContent = msg;
  statusEl.className = 'precos-status ' + (ok ? 'ok' : 'err');
  if(ok){
    setTimeout(() => { statusEl.textContent = ''; statusEl.className = 'precos-status'; }, 3000);
  }
}

function criarElemento(tag, attrs = {}, texto){
  const e = document.createElement(tag);
  for(const [k, v] of Object.entries(attrs)){
    if(k === 'class') e.className = v;
    else e.setAttribute(k, v);
  }
  if(texto !== undefined) e.textContent = texto;
  return e;
}

async function criarEditorTabela({containerId, endpoint, titulo, colunas, campoMultiplo = null}){
  const container = document.getElementById(containerId);
  container.innerHTML = `
    <div class="card-head"><h2>${titulo}</h2><span class="tag" id="${containerId}-count">…</span></div>
    <div class="tabela-wrap"><table class="tabela-editor"><thead></thead><tbody></tbody></table></div>
    <div class="precos-status"></div>
  `;
  const thead = container.querySelector('thead');
  const tbody = container.querySelector('tbody');
  const statusEl = container.querySelector('.precos-status');
  const countTag = document.getElementById(`${containerId}-count`);

  const headRow = document.createElement('tr');
  colunas.forEach(c => headRow.appendChild(criarElemento('th', {}, c.label)));
  headRow.appendChild(criarElemento('th', {}, 'Ações'));
  thead.appendChild(headRow);

  const mostrarStatus = (msg, ok) => mostrarStatusPrecos(statusEl, msg, ok);

  function criarInputs(dados = {}, opts = {}){
    return colunas.map(c => {
      if(c.tipo === 'select'){
        const select = document.createElement('select');
        // Opção pode ser uma string simples (valor = texto exibido, caso
        // mais comum: veículo, UF, tipo...) ou um objeto {value, label}
        // quando o valor salvo (ex: praca_id, um FK numérico) precisa ser
        // diferente do texto mostrado pro usuário (ex: "BR-101 — Praça X").
        c.opcoes.forEach(op => {
          const option = document.createElement('option');
          option.value = (op && typeof op === 'object') ? op.value : op;
          option.textContent = (op && typeof op === 'object') ? op.label : op;
          select.appendChild(option);
        });
        const primeiraOpcao = (c.opcoes[0] && typeof c.opcoes[0] === 'object') ? c.opcoes[0].value : c.opcoes[0];
        select.value = dados[c.campo] ?? primeiraOpcao;
        return select;
      }
      const input = document.createElement('input');
      if(c.tipo === 'moeda'){
        input.type = 'text';
        input.inputMode = 'decimal';
        input.value = dados[c.campo] != null ? formatarValorMoeda(dados[c.campo]) : '';
        input.addEventListener('input', () => formatarMoedaDigitando(input));
      }else{
        input.type = c.tipo === 'text' ? 'text' : 'number';
        if(c.tipo !== 'text') input.step = c.step || 'any';
        input.value = dados[c.campo] ?? '';
      }
      input.placeholder = (opts.multiplo && campoMultiplo && c.campo === campoMultiplo)
        ? `${c.label} (separe por vírgula pra adicionar em várias de uma vez)`
        : c.label;
      return input;
    });
  }

  function lerValores(inputs){
    const obj = {};
    colunas.forEach((c, i) => {
      const bruto = inputs[i].value;
      if(c.tipo === 'select'){
        // c.numerico: o valor salvo no <select> é um FK numérico (ex:
        // praca_id), não texto -- ver comentário em criarInputs.
        obj[c.campo] = c.numerico ? Number(bruto) : bruto;
        return;
      }
      if(c.tipo === 'text'){
        obj[c.campo] = bruto;
        return;
      }
      if(bruto === ''){
        // Não força 0: omite o campo pra deixar a API aplicar o próprio
        // padrão (ex: "Até (kg)" de veículo cai pra 999999) ou, se o
        // campo não tiver padrão, retornar um erro claro de "obrigatório"
        // em vez de aceitar silenciosamente um 0 que não foi digitado.
        return;
      }
      obj[c.campo] = c.tipo === 'moeda' ? valorMoedaParaNumero(bruto) : parseFloat(bruto);
    });
    return obj;
  }

  async function carregar(){
    tbody.innerHTML = '';
    let itens = [];
    try{
      const res = await fetch(`${API_BASE}/admin/${endpoint}`);
      if(!res.ok) throw new Error(`Erro HTTP ${res.status}`);
      itens = await res.json();
    }catch(e){
      mostrarStatus('Falha ao carregar dados desta tabela.', false);
      countTag.textContent = 'erro';
      return;
    }

    // Uma linha por item, com os botões Salvar/Excluir já ligados --
    // extraída pra função porque também é usada pra inserir a(s) linha(s)
    // recém-criada(s) sem precisar recarregar a tabela inteira (ver
    // btnAdd abaixo).
    function criarLinhaItem(item){
      const tr = document.createElement('tr');
      const inputs = criarInputs(item);
      inputs.forEach(inp => {
        const td = document.createElement('td');
        td.appendChild(inp);
        tr.appendChild(td);
      });

      const tdAcoes = document.createElement('td');
      tdAcoes.className = 'col-acoes';

      const btnSalvar = criarElemento('button', {type: 'button', class: 'btn-icone'}, '💾 Salvar');
      btnSalvar.addEventListener('click', async () => {
        btnSalvar.disabled = true;
        try{
          const dados = lerValores(inputs);
          const res = await fetch(`${API_BASE}/admin/${endpoint}/${item.id}`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(dados),
          });
          const data = await res.json();
          if(!res.ok) throw new Error(data.detail || 'Erro ao salvar.');
          mostrarStatus('Linha salva.', true);
        }catch(e){ mostrarStatus(e.message, false); }
        finally{ btnSalvar.disabled = false; }
      });

      const btnExcluir = criarElemento('button', {type: 'button', class: 'btn-icone excluir'}, '🗑 Excluir');
      btnExcluir.addEventListener('click', async () => {
        if(!confirm('Excluir esta linha? Essa ação não pode ser desfeita.')) return;
        btnSalvar.disabled = true;
        btnExcluir.disabled = true;
        try{
          const res = await fetch(`${API_BASE}/admin/${endpoint}/${item.id}`, {method: 'DELETE'});
          if(!res.ok){
            const data = await res.json();
            throw new Error(data.detail || 'Erro ao excluir.');
          }
          // Remove só essa linha em vez de recarregar a tabela inteira --
          // o restante das linhas não mudou.
          tr.remove();
          atualizarContagem();
          mostrarStatus('Linha excluída.', true);
        }catch(e){
          mostrarStatus(e.message, false);
          btnSalvar.disabled = false;
          btnExcluir.disabled = false;
        }
      });

      tdAcoes.appendChild(btnSalvar);
      tdAcoes.appendChild(btnExcluir);
      tr.appendChild(tdAcoes);
      return tr;
    }

    function atualizarContagem(){
      const n = tbody.querySelectorAll('tr:not(.linha-nova)').length;
      countTag.textContent = `${n} linha${n === 1 ? '' : 's'}`;
    }

    itens.forEach(item => tbody.appendChild(criarLinhaItem(item)));
    atualizarContagem();

    // Linha para adicionar um novo registro
    const trNova = document.createElement('tr');
    trNova.className = 'linha-nova';
    const inputsNovos = criarInputs({}, {multiplo: true});
    inputsNovos.forEach(inp => {
      const td = document.createElement('td');
      td.appendChild(inp);
      trNova.appendChild(td);
    });
    const tdAcoesNova = document.createElement('td');
    const btnAdd = criarElemento('button', {type: 'button', class: 'btn-icone'}, '+ Adicionar');
    btnAdd.addEventListener('click', async () => {
      btnAdd.disabled = true;
      try{
        const dados = lerValores(inputsNovos);

        // Se o campo múltiplo (ex: "cidade") tiver vírgula, cria uma
        // linha separada pra cada valor, todas com o resto igual —
        // ex: "São Paulo, Rio de Janeiro, Minas Gerais" na mesma taxa.
        let alvos = [dados];
        if(campoMultiplo && typeof dados[campoMultiplo] === 'string' && dados[campoMultiplo].includes(',')){
          const valores = dados[campoMultiplo].split(',').map(v => v.trim()).filter(Boolean);
          alvos = valores.map(v => ({...dados, [campoMultiplo]: v}));
        }

        const sucesso = [];
        const falhas = [];
        for(const item of alvos){
          try{
            const res = await fetch(`${API_BASE}/admin/${endpoint}`, {
              method: 'POST',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify(item),
            });
            const data = await res.json();
            if(!res.ok) throw new Error(data.detail || 'Erro ao adicionar.');
            // Insere a linha nova direto antes da "linha de adicionar",
            // sem recarregar a tabela inteira -- data já vem com o id
            // atribuído pelo backend.
            tbody.insertBefore(criarLinhaItem(data), trNova);
            sucesso.push(campoMultiplo ? item[campoMultiplo] : '');
          }catch(e){
            falhas.push(`${campoMultiplo ? item[campoMultiplo] : ''}: ${e.message}`.trim());
          }
        }

        atualizarContagem();
        if(falhas.length === 0){
          mostrarStatus(alvos.length > 1 ? `${sucesso.length} linhas adicionadas.` : 'Linha adicionada.', true);
          inputsNovos.forEach((inp, i) => {
            if(colunas[i].tipo !== 'select'){ inp.value = ''; return; }
            const primeiraOpcao = colunas[i].opcoes[0];
            inp.value = (primeiraOpcao && typeof primeiraOpcao === 'object') ? primeiraOpcao.value : primeiraOpcao;
          });
        }else if(sucesso.length === 0){
          mostrarStatus(`Nada adicionado — ${falhas.join(' | ')}`, false);
        }else{
          mostrarStatus(`${sucesso.length} adicionada(s). Falharam: ${falhas.join(' | ')}`, false);
        }
      }catch(e){ mostrarStatus(e.message, false); }
      finally{ btnAdd.disabled = false; }
    });
    tdAcoesNova.appendChild(btnAdd);
    trNova.appendChild(tdAcoesNova);
    tbody.appendChild(trNova);
  }

  await carregar();
}

let precosCarregado = false;

// Busca que varre de uma vez todas as tabelas (e o card de PIS/COFINS) da
// Tabela de Preços -- útil porque a página tem mais de 15 tabelas
// espalhadas em 6 seções recolhíveis, seria fácil perder algo procurando
// manualmente seção por seção. Ao digitar, abre e mostra só as seções
// com resultado; ao limpar, devolve cada seção pro estado (aberta ou
// fechada) que já estava antes de começar a buscar.
let precosBuscaEstadoAnterior = null; // null = não tá em modo busca

function filtrarTabelaPrecos(){
  const termo = document.getElementById('precos-busca').value.trim().toLowerCase();
  const secoes = [...document.querySelectorAll('.precos-section-toggle')];
  const avisoVazio = document.getElementById('precos-busca-vazio');

  if(!termo){
    document.querySelectorAll('#view-precos tbody tr').forEach(tr => { tr.style.display = ''; });
    document.querySelectorAll('#view-precos .precos-card').forEach(card => { card.style.display = ''; });
    secoes.forEach(header => {
      const bloco = document.getElementById(header.dataset.target);
      const icon = header.querySelector('.precos-section-icon');
      header.style.display = '';
      const abrir = precosBuscaEstadoAnterior ? precosBuscaEstadoAnterior[header.dataset.target] : (bloco.style.display !== 'none');
      bloco.style.display = abrir ? '' : 'none';
      icon.classList.toggle('ti-chevron-down', abrir);
      icon.classList.toggle('ti-chevron-right', !abrir);
    });
    precosBuscaEstadoAnterior = null;
    avisoVazio.style.display = 'none';
    return;
  }

  if(precosBuscaEstadoAnterior === null){
    // Primeira letra digitada: guarda o estado atual de cada seção pra
    // devolver depois, quando a busca for limpa.
    precosBuscaEstadoAnterior = {};
    secoes.forEach(header => {
      const bloco = document.getElementById(header.dataset.target);
      precosBuscaEstadoAnterior[header.dataset.target] = bloco.style.display !== 'none';
    });
  }

  let totalVisivel = 0;
  secoes.forEach(header => {
    const bloco = document.getElementById(header.dataset.target);
    const icon = header.querySelector('.precos-section-icon');
    let algumCardVisivel = false;

    bloco.querySelectorAll(':scope > .precos-card').forEach(card => {
      const tabela = card.querySelector('.tabela-editor');
      let cardBate;

      if(tabela){
        const titulo = card.querySelector('.card-head h2')?.textContent.toLowerCase() || '';
        const tituloBate = titulo.includes(termo);
        let algumaLinhaBate = false;

        card.querySelectorAll('tbody tr').forEach(tr => {
          if(tr.classList.contains('linha-nova')){ tr.style.display = ''; return; } // linha de adicionar fica sempre disponível
          if(tituloBate){ tr.style.display = ''; algumaLinhaBate = true; return; }
          const texto = [...tr.querySelectorAll('input, select')]
            .map(el => el.tagName === 'SELECT' ? (el.selectedOptions[0]?.textContent || '') : el.value)
            .join(' ').toLowerCase();
          const bate = texto.includes(termo);
          tr.style.display = bate ? '' : 'none';
          if(bate) algumaLinhaBate = true;
        });

        cardBate = tituloBate || algumaLinhaBate;
      }else{
        // Cards sem tabela (ex: PIS/COFINS) -- casa pelo texto do card
        // inteiro (labels e observação).
        cardBate = card.textContent.toLowerCase().includes(termo);
      }

      card.style.display = cardBate ? '' : 'none';
      if(cardBate) algumCardVisivel = true;
    });

    header.style.display = algumCardVisivel ? '' : 'none';
    bloco.style.display = algumCardVisivel ? '' : 'none';
    if(algumCardVisivel){
      icon.classList.add('ti-chevron-down');
      icon.classList.remove('ti-chevron-right');
      totalVisivel++;
    }
  });

  avisoVazio.style.display = totalVisivel === 0 ? '' : 'none';
}

document.getElementById('precos-busca').addEventListener('input', filtrarTabelaPrecos);

// ============================================================
// Histórico de orçamentos
// ============================================================
let historicoCache = [];

async function carregarHistorico(){
  const contagemEl = document.getElementById('historico-contagem');
  const listaEl = document.getElementById('historico-lista');
  contagemEl.textContent = 'Carregando...';
  try{
    const res = await fetch(`${API_BASE}/historico`);
    if(!res.ok) throw new Error(`Erro HTTP ${res.status}`);
    historicoCache = await res.json();
    contagemEl.textContent = `${historicoCache.length} orçamento${historicoCache.length === 1 ? '' : 's'} salvo${historicoCache.length === 1 ? '' : 's'}`;
    popularFiltrosHistorico(historicoCache);
    aplicarFiltrosHistorico();
  }catch(e){
    contagemEl.textContent = 'Erro ao carregar o histórico.';
    listaEl.innerHTML = `<div style="padding:20px;color:var(--err);font-size:13px;">${esc(e.message)}</div>`;
  }
}

function renderizarHistorico(lista){
  const listaEl = document.getElementById('historico-lista');
  if(lista.length === 0){
    listaEl.innerHTML = `<div style="padding:32px 20px;text-align:center;color:var(--text-dim);font-size:13px;">
      Nenhum orçamento salvo ainda. Calcule um orçamento e clique em "Salvar no histórico" pra ele aparecer aqui.
    </div>`;
    return;
  }

  const statusCor = {'Fechado': 'var(--ok)', 'Pendente': 'var(--warn)', 'Cancelado': 'var(--err)'};
  const colunas = '82px 1.15fr 78px 1fr 100px 130px 90px 40px';

  const cabecalho = `<div style="display:grid;grid-template-columns:${colunas};padding:9px 20px;font-size:10px;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-dim);border-bottom:1px solid var(--border-soft);">
    <span>Código</span><span>Cliente</span><span>Data</span><span>Rota</span><span>Valor</span><span>Responsável</span><span>Status</span><span></span>
  </div>`;

  const linhas = lista.map(o => {
    const data = new Date(o.criado_em);
    const dataFmt = isNaN(data) ? o.criado_em : data.toLocaleDateString('pt-BR', {day:'2-digit', month:'2-digit'});
    const rota = esc([o.origem_resumo, o.destino_resumo].filter(Boolean).join(' → ') || '—');
    const iniciais = esc((o.responsavel || '?').trim().split(/\s+/).slice(0,2).map(p => p[0]).join('').toUpperCase());
    const cor = statusCor[o.status] || 'var(--text-dim)';
    // Só quem salvou o registro (mesma conta logada) ou um admin pode
    // excluir — o backend já recusa (403) quem não pode, isso aqui só
    // evita mostrar um botão que vai dar erro pro usuário comum.
    const podeExcluir = !!currentUser && (currentUser.role === 'admin' || o.criado_por === currentUser.username);
    const botaoExcluir = podeExcluir
      ? `<button type="button" class="historico-excluir" data-id="${esc(o.id)}" title="Excluir" style="background:none;border:none;color:var(--text-dim);cursor:pointer;padding:4px;">
          <i class="ti ti-trash"></i>
        </button>`
      : '<span></span>';
    return `<div class="historico-row" data-codigo="${esc(o.codigo)}" style="display:grid;grid-template-columns:${colunas};align-items:center;padding:12px 20px;font-size:12.5px;color:var(--text);border-bottom:1px solid var(--border-soft);cursor:pointer;">
      <span style="color:var(--accent-strong);font-weight:600;">${esc(o.codigo)}</span>
      <span>${esc(o.cliente) || '—'}</span>
      <span style="color:var(--text-dim);">${esc(dataFmt)}</span>
      <span style="color:var(--text-dim);">${rota}</span>
      <span style="font-weight:600;">${fmtBRL(o.frete_total)}</span>
      <span style="display:flex;align-items:center;gap:6px;color:var(--text-dim);">
        <span style="width:18px;height:18px;border-radius:50%;background:var(--panel-alt);color:var(--accent-strong);font-size:9px;font-weight:700;display:flex;align-items:center;justify-content:center;flex-shrink:0;">${iniciais}</span>
        ${esc(o.responsavel) || '—'}
      </span>
      <span style="display:inline-flex;align-items:center;gap:5px;font-size:11.5px;">
        <span style="width:7px;height:7px;border-radius:50%;background:${cor};display:inline-block;"></span>${esc(o.status)}
      </span>
      ${botaoExcluir}
    </div>`;
  }).join('');

  listaEl.innerHTML = cabecalho + linhas;

  listaEl.querySelectorAll('.historico-row').forEach(row => {
    row.addEventListener('click', (ev) => {
      if(ev.target.closest('.historico-excluir')) return;
      abrirDetalheHistorico(row.dataset.codigo);
    });
  });
  listaEl.querySelectorAll('.historico-excluir').forEach(btn => {
    btn.addEventListener('click', async (ev) => {
      ev.stopPropagation();
      if(!confirm('Excluir este orçamento do histórico? Essa ação não pode ser desfeita.')) return;
      const statusEl = document.getElementById('historico-lista-status');
      btn.disabled = true;
      try{
        const res = await fetch(`${API_BASE}/historico/${btn.dataset.id}`, {method: 'DELETE'});
        if(!res.ok) throw new Error(`Erro HTTP ${res.status}`);
        statusEl.className = 'cep-info';
        statusEl.textContent = '';
        await carregarHistorico();
      }catch(e){
        statusEl.className = 'cep-info err';
        statusEl.textContent = `Erro ao excluir: ${e.message}`;
        btn.disabled = false;
      }
    });
  });
}

// Preenche os dropdowns de Responsável e Veículo só com valores que
// aparecem de verdade no histórico carregado -- evita opção que nunca dá
// resultado nenhum. Preserva a seleção atual se ela continuar entre as
// opções novas (ex: depois de recarregar o histórico).
function popularFiltrosHistorico(lista){
  const selResponsavel = document.getElementById('historico-filtro-responsavel');
  const selVeiculo = document.getElementById('historico-filtro-veiculo');
  const valorAtualResp = selResponsavel.value;
  const valorAtualVeic = selVeiculo.value;

  const responsaveis = [...new Set(lista.map(o => o.responsavel).filter(Boolean))].sort();
  const veiculos = [...new Set(lista.map(o => o.veiculo).filter(Boolean))].sort();

  selResponsavel.innerHTML = '<option value="">Responsável: todos</option>' +
    responsaveis.map(r => `<option value="${esc(r)}">${esc(r)}</option>`).join('');
  selVeiculo.innerHTML = '<option value="">Veículo: todos</option>' +
    veiculos.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join('');

  if(responsaveis.includes(valorAtualResp)) selResponsavel.value = valorAtualResp;
  if(veiculos.includes(valorAtualVeic)) selVeiculo.value = valorAtualVeic;
}

// Combina a busca por texto com os filtros de status/responsável/veículo/
// período -- todos em conjunto (E lógico), lendo direto dos controles do
// DOM em vez de guardar o estado em variáveis separadas.
function aplicarFiltrosHistorico(){
  const termo = document.getElementById('historico-busca').value.trim().toLowerCase();
  const status = document.getElementById('historico-filtro-status').value;
  const responsavel = document.getElementById('historico-filtro-responsavel').value;
  const veiculo = document.getElementById('historico-filtro-veiculo').value;
  const dataDe = document.getElementById('historico-filtro-data-de').value;
  const dataAte = document.getElementById('historico-filtro-data-ate').value;

  const filtrado = historicoCache.filter(o => {
    if(termo){
      const bate = (o.cliente || '').toLowerCase().includes(termo) ||
        (o.codigo || '').toLowerCase().includes(termo) ||
        (o.responsavel || '').toLowerCase().includes(termo);
      if(!bate) return false;
    }
    if(status && o.status !== status) return false;
    if(responsavel && o.responsavel !== responsavel) return false;
    if(veiculo && o.veiculo !== veiculo) return false;
    if(dataDe || dataAte){
      const dataOrc = (o.criado_em || '').slice(0, 10); // "AAAA-MM-DD", mesmo formato do <input type="date">
      if(dataDe && dataOrc < dataDe) return false;
      if(dataAte && dataOrc > dataAte) return false;
    }
    return true;
  });
  renderizarHistorico(filtrado);
}

document.getElementById('historico-busca').addEventListener('input', aplicarFiltrosHistorico);
document.getElementById('historico-filtro-status').addEventListener('change', aplicarFiltrosHistorico);
document.getElementById('historico-filtro-responsavel').addEventListener('change', aplicarFiltrosHistorico);
document.getElementById('historico-filtro-veiculo').addEventListener('change', aplicarFiltrosHistorico);
document.getElementById('historico-filtro-data-de').addEventListener('change', aplicarFiltrosHistorico);
document.getElementById('historico-filtro-data-ate').addEventListener('change', aplicarFiltrosHistorico);
document.getElementById('historico-filtro-limpar').addEventListener('click', () => {
  document.getElementById('historico-busca').value = '';
  document.getElementById('historico-filtro-status').value = '';
  document.getElementById('historico-filtro-responsavel').value = '';
  document.getElementById('historico-filtro-veiculo').value = '';
  document.getElementById('historico-filtro-data-de').value = '';
  document.getElementById('historico-filtro-data-ate').value = '';
  renderizarHistorico(historicoCache);
});

let detalheHistoricoCodigo = null;
let detalheHistoricoRegistro = null;

function renderizarDetalheHistorico(registro){
  const calc = registro.dados?.resultado?.calculos_intermediarios || {};
  const entrada = registro.dados?.resultado?.entrada || {};

  document.getElementById('detalhe-titulo').textContent = `${registro.codigo} — ${registro.cliente}`;
  document.getElementById('detalhe-subtitulo').textContent =
    `Responsável: ${registro.responsavel} · ${new Date(registro.criado_em).toLocaleString('pt-BR')}`;

  const linhas = [
    ['Rota', [registro.origem_resumo, registro.destino_resumo].filter(Boolean).join(' → ') || '—'],
    ['Veículo', registro.veiculo || entrada.veiculo || '—'],
  ];
  if(entrada.distancia_coleta_km > 0){
    linhas.push(['KM de coleta', `${entrada.distancia_coleta_km} km`]);
  }
  // registro.distancia_km é a distância total salva (pode incluir trecho
  // de balsa, ex: Belém -> Manaus, que o veículo não roda -- ver
  // calc.distancia_balsa_km); calc.distancia_faturavel_km já exclui esse
  // trecho. Orçamentos salvos antes desse campo existir caem no valor
  // total mesmo (fallback).
  const kmTransferenciaHistorico = calc.distancia_faturavel_km ?? registro.distancia_km;
  linhas.push(['KM de transferência', `${kmTransferenciaHistorico} km`]);
  if(calc.distancia_retorno_km > 0){
    linhas.push(['KM de retorno vazio', `${calc.distancia_retorno_km} km`]);
  }
  linhas.push(['Peso considerado', calc.peso_considerado_kg != null ? `${calc.peso_considerado_kg} kg` : '—']);
  if(calc.custo_extra_total > 0){
    const nomesCustosExtras = (calc.custos_extras || []).map(c => c.categoria).join(', ');
    linhas.push(['Custos extras', `${fmtBRL(calc.custo_extra_total)}${nomesCustosExtras ? ` (${nomesCustosExtras})` : ''}`]);
  }
  if(calc.margem_lucro_pct != null){
    linhas.push(['Margem de lucro', `${fmtBRL(calc.valor_margem_lucro)} (${calc.margem_lucro_pct}%)`]);
  }
  linhas.push(
    ['Valor da mercadoria', fmtBRL(registro.valor_mercadoria)],
    ['Frete total', fmtBRL(registro.frete_total)],
  );
  document.getElementById('detalhe-conteudo').innerHTML = linhas.map(([label, valor]) => `
    <div class="line"><span>${esc(label)}</span><span>${esc(valor)}</span></div>
  `).join('');

  // Só quem salvou o registro (mesma conta logada) ou um admin pode editar
  // o pedágio -- mesma regra usada pra excluir (ver renderizarHistorico).
  // O backend também recusa (403) quem não pode, isso aqui só evita
  // mostrar um campo que vai dar erro pro usuário comum.
  const podeEditar = !!currentUser && (currentUser.role === 'admin' || registro.criado_por === currentUser.username);
  const blocoEditarPedagio = document.getElementById('detalhe-editar-pedagio');
  blocoEditarPedagio.style.display = podeEditar ? '' : 'none';
  if(podeEditar){
    document.getElementById('detalhe-pedagio').value = formatarValorMoeda(calc.pedagio || 0);
    document.getElementById('detalhe-pedagio-status').textContent = '';
  }

  renderizarMemoriaCalculo(registro.dados?.resultado, 'detalhe-memoria-calculo', false);
  renderizarAlteracoesHistorico(registro.alteracoes || []);
}

const CAMPOS_ALTERACAO_HISTORICO = { pedagio: 'Pedágio' };

function renderizarAlteracoesHistorico(alteracoes){
  const card = document.getElementById('detalhe-alteracoes-card');
  if(!alteracoes.length){
    card.style.display = 'none';
    return;
  }
  card.style.display = '';
  document.getElementById('detalhe-alteracoes').innerHTML = alteracoes.map(a => {
    const campo = CAMPOS_ALTERACAO_HISTORICO[a.campo] || a.campo;
    const quando = new Date(a.alterado_em).toLocaleString('pt-BR');
    return `<div class="line">
      <span>${esc(campo)} alterado por ${esc(a.alterado_por || '—')} em ${esc(quando)}</span>
      <span>${esc(fmtBRL(a.valor_antigo))} → ${esc(fmtBRL(a.valor_novo))}</span>
    </div>`;
  }).join('');
}

async function abrirDetalheHistorico(codigo){
  const statusListaEl = document.getElementById('historico-lista-status');
  try{
    const res = await fetch(`${API_BASE}/historico/${codigo}`);
    if(!res.ok) throw new Error(`Erro HTTP ${res.status}`);
    const registro = await res.json();
    detalheHistoricoCodigo = registro.codigo;
    detalheHistoricoRegistro = registro;

    renderizarDetalheHistorico(registro);

    statusListaEl.className = 'cep-info';
    statusListaEl.textContent = '';
    const statusDetalheEl = document.getElementById('detalhe-status');
    statusDetalheEl.className = 'cep-info';
    statusDetalheEl.textContent = '';
    document.getElementById('view-historico').style.display = 'none';
    document.getElementById('view-historico-detalhe').style.display = 'block';
  }catch(e){
    statusListaEl.className = 'cep-info err';
    statusListaEl.textContent = `Erro ao abrir o orçamento: ${e.message}`;
  }
}

document.getElementById('btn-salvar-pedagio-historico').addEventListener('click', async () => {
  if(!detalheHistoricoRegistro) return;
  const btn = document.getElementById('btn-salvar-pedagio-historico');
  const statusEl = document.getElementById('detalhe-pedagio-status');
  const novoPedagio = valorMoedaParaNumero(document.getElementById('detalhe-pedagio').value);

  btn.disabled = true;
  statusEl.className = 'cep-info';
  statusEl.textContent = 'Salvando...';
  try{
    const res = await fetch(`${API_BASE}/historico/${detalheHistoricoRegistro.id}/pedagio`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({pedagio: novoPedagio}),
    });
    const data = await res.json();
    if(!res.ok) throw new Error(data.detail || 'Erro ao salvar o pedágio.');

    // Atualiza o registro em memória com o que o backend recalculou
    // (frete_total pode ter mudado pela diferença do pedágio) e
    // re-renderiza o detalhe pra refletir o novo total sem recarregar.
    detalheHistoricoRegistro.frete_total = data.frete_total;
    if(detalheHistoricoRegistro.dados?.resultado?.calculos_intermediarios){
      detalheHistoricoRegistro.dados.resultado.calculos_intermediarios.pedagio = data.pedagio;
    }
    if(detalheHistoricoRegistro.dados?.resultado?.resultado){
      detalheHistoricoRegistro.dados.resultado.resultado.frete_total = data.frete_total;
    }
    renderizarDetalheHistorico(detalheHistoricoRegistro);

    statusEl.className = 'cep-info ok';
    statusEl.textContent = 'Pedágio atualizado.';
  }catch(e){
    statusEl.className = 'cep-info err';
    statusEl.textContent = e.message;
  }finally{
    btn.disabled = false;
  }
});

document.getElementById('btn-voltar-historico').addEventListener('click', () => {
  document.getElementById('view-historico-detalhe').style.display = 'none';
  document.getElementById('view-historico').style.display = 'block';
});

document.getElementById('btn-exportar-planilha').addEventListener('click', async (ev) => {
  if(!detalheHistoricoCodigo) return;
  const btn = ev.currentTarget;
  const statusEl = document.getElementById('detalhe-status');
  const textoOriginal = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = 'Gerando...';
  statusEl.className = 'cep-info';
  statusEl.textContent = '';
  try{
    const res = await fetch(`${API_BASE}/historico/${detalheHistoricoCodigo}/planilha`);
    if(!res.ok){
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || `Erro HTTP ${res.status}`);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `Orcamento_${detalheHistoricoCodigo}.xlsx`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }catch(e){
    statusEl.className = 'cep-info err';
    statusEl.textContent = `Erro ao exportar planilha: ${e.message}`;
  }finally{
    btn.disabled = false;
    btn.innerHTML = textoOriginal;
  }
});

const configPracasPedagio = {
  containerId: 'precos-pracas-pedagio', endpoint: 'pracas-pedagio',
  titulo: 'Praças de Pedágio (preço por número de eixos do veículo)',
  colunas: [
    {campo: 'nome', label: 'Nome da praça', tipo: 'text'},
    {campo: 'rodovia', label: 'Rodovia', tipo: 'text'},
    {campo: 'concessionaria', label: 'Concessionária', tipo: 'text'},
    {campo: 'uf', label: 'UF', tipo: 'text'},
    {campo: 'km', label: 'Km', tipo: 'text'},
    {campo: 'valor_eixo_2', label: '2 eixos (R$)', tipo: 'moeda'},
    {campo: 'valor_eixo_3', label: '3 eixos (R$)', tipo: 'moeda'},
    {campo: 'valor_eixo_4', label: '4 eixos (R$)', tipo: 'moeda'},
    {campo: 'valor_eixo_5', label: '5 eixos (R$)', tipo: 'moeda'},
    {campo: 'valor_eixo_6', label: '6 eixos (R$)', tipo: 'moeda'},
    {campo: 'valor_eixo_7', label: '7 eixos (R$)', tipo: 'moeda'},
    {campo: 'valor_eixo_8', label: '8 eixos (R$)', tipo: 'moeda'},
    {campo: 'valor_eixo_9', label: '9 eixos (R$)', tipo: 'moeda'},
    {campo: 'observacao', label: 'Observação', tipo: 'text'},
  ],
};

// Carrega (ou recarrega, depois de um import CSV) o card de Praças de
// Pedágio e reanexa o bloco de import CSV embaixo dele -- criarEditorTabela
// substitui todo o innerHTML do container, então o bloco de import precisa
// ser reanexado toda vez.
async function carregarBlocoPisCofins(){
  const aliquotaInput = document.getElementById('pis-cofins-aliquota');
  const observacaoInput = document.getElementById('pis-cofins-observacao');
  const statusEl = document.getElementById('pis-cofins-status');
  const btn = document.getElementById('btn-salvar-pis-cofins');

  try{
    const res = await fetch(`${API_BASE}/admin/pis-cofins`);
    const data = await res.json();
    if(!res.ok) throw new Error(data.detail || 'Falha ao carregar a alíquota de PIS/COFINS.');
    aliquotaInput.value = data.aliquota;
    observacaoInput.value = data.observacao || '';
  }catch(e){
    statusEl.className = 'geo-status err';
    statusEl.textContent = e.message;
    btn.disabled = true;
  }

  btn.addEventListener('click', async () => {
    btn.disabled = true;
    statusEl.className = 'geo-status';
    statusEl.textContent = 'Salvando...';
    try{
      const res = await fetch(`${API_BASE}/admin/pis-cofins`, {
        method: 'PUT', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          aliquota: parseFloat(aliquotaInput.value) || 0,
          observacao: observacaoInput.value,
        }),
      });
      const data = await res.json();
      if(!res.ok) throw new Error(data.detail || 'Falha ao salvar.');
      statusEl.classList.add('ok');
      statusEl.textContent = 'Alíquota salva com sucesso.';
    }catch(e){
      statusEl.classList.add('err');
      statusEl.textContent = e.message;
    }finally{
      btn.disabled = false;
    }
  });
}

async function carregarBlocoPracasPedagio(){
  await criarEditorTabela(configPracasPedagio);
  montarImportCsvPracasPedagio();
}

function montarImportCsvPracasPedagio(){
  const container = document.getElementById('precos-pracas-pedagio');
  const bloco = document.createElement('div');
  bloco.style.cssText = 'padding:12px 20px;border-top:1px solid var(--border-soft);display:flex;align-items:center;gap:10px;flex-wrap:wrap;';

  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.csv,text/csv';

  const btn = criarElemento('button', {type: 'button', class: 'btn-icone'}, '📥 Importar CSV');
  const statusEl = document.createElement('span');
  statusEl.style.cssText = 'font-size:11.5px;color:var(--text-dim);';

  btn.addEventListener('click', async () => {
    if(!input.files || !input.files[0]){
      statusEl.textContent = 'Escolha um arquivo CSV primeiro.';
      return;
    }
    btn.disabled = true;
    statusEl.textContent = 'Importando...';
    try{
      const conteudo = await input.files[0].text();
      const res = await fetch(`${API_BASE}/admin/pracas-pedagio/importar-csv`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({conteudo}),
      });
      const data = await res.json();
      if(!res.ok) throw new Error(data.detail || 'Erro ao importar.');
      const erros = (data.erros && data.erros.length) ? ` — ${data.erros.length} erro(s): ${data.erros.join(' | ')}` : '';
      statusEl.textContent = `${data.criadas} criada(s), ${data.atualizadas} atualizada(s).${erros}`;
      await carregarBlocoPracasPedagio();
    }catch(e){
      statusEl.textContent = `Erro ao importar: ${e.message}`;
      btn.disabled = false;
    }
  });

  bloco.appendChild(input);
  bloco.appendChild(btn);
  bloco.appendChild(statusEl);
  container.appendChild(bloco);
}

async function carregarTabelaPrecos(){
  if(precosCarregado) return;
  precosCarregado = true;

  // Listas cruas de filiais/veículos/praças pras colunas <select> das
  // tabelas que dependem delas (faixas-km-veiculo, coleta-cidades-fixas,
  // taxas-balsa, pedagios-rota) -- buscadas em paralelo com as tabelas
  // independentes abaixo, já que não têm relação nenhuma com elas.
  const filiaisVeiculosPromise = Promise.all([
    fetch(`${API_BASE}/admin/filiais`).then(r => r.json()).catch(() => []),
    fetch(`${API_BASE}/admin/veiculos`).then(r => r.json()).catch(() => []),
    fetch(`${API_BASE}/parametros/pracas-pedagio`).then(r => r.json()).catch(() => []),
  ]);

  // Tabelas sem dependência entre si -- rodam em paralelo em vez de
  // esperar uma terminar pra começar a próxima (eram ~9 idas e voltas
  // sequenciais ao servidor; agora é só a mais lenta delas).
  await Promise.all([
    criarEditorTabela({
      containerId: 'precos-filiais', endpoint: 'filiais',
      titulo: 'Filiais (editar o endereço já força nova geocodificação)',
      colunas: [
        {campo: 'nome', label: 'Nome (usado como cidade de referência)', tipo: 'text'},
        {campo: 'endereco', label: 'Endereço completo (rua, número, bairro, cidade, UF, CEP)', tipo: 'text'},
        {campo: 'uf', label: 'UF (obrigatória — usada no cálculo de ICMS)', tipo: 'select', opcoes: [{value: '', label: 'Selecione a UF...'}, ...UFS_BRASIL]},
      ],
    }),

    criarEditorTabela({
      containerId: 'precos-veiculos', endpoint: 'veiculos', titulo: 'Veículos (escolhidos automaticamente pelo peso)',
      colunas: [
        {campo: 'nome', label: 'Nome', tipo: 'text'},
        {campo: 'de', label: 'De (kg)', tipo: 'number', step: '1'},
        {campo: 'ate', label: 'Até (kg)', tipo: 'number', step: '1'},
        {campo: 'tarifa_km', label: 'Tarifa/km (R$)', tipo: 'moeda'},
        {campo: 'valor_tonelada_excedente', label: 'Valor/tonelada excedente (R$)', tipo: 'moeda'},
        {campo: 'tarifa_km_retorno', label: 'Retorno vazio (R$/km)', tipo: 'moeda'},
        {campo: 'tarifa_km_manutencao', label: 'Manutenção (R$/km, ida + coleta própria + retorno vazio)', tipo: 'moeda'},
        {campo: 'capacidade_m3', label: 'Capacidade útil (m³)', tipo: 'number', step: '0.01'},
        {campo: 'percentual_capacidade_util', label: '% da capacidade que pode ocupar', tipo: 'number', step: '1'},
        {campo: 'numero_eixos', label: 'Nº de eixos (pra achar o pedágio nas praças cadastradas)', tipo: 'number', step: '1'},
        {campo: 'observacao', label: 'Observação', tipo: 'text'},
      ],
    }),

    carregarBlocoPracasPedagio(),
    carregarBlocoPisCofins(),

    criarEditorTabela({
      containerId: 'precos-taxas-adicionais', endpoint: 'taxas-adicionais', titulo: 'Taxas Adicionais',
      colunas: [
        {campo: 'nome', label: 'Nome', tipo: 'text'},
        {campo: 'tipo', label: 'Tipo', tipo: 'select', opcoes: ['fixo', 'percentual']},
        {campo: 'valor', label: 'Valor (R$ se fixo, % se percentual)', tipo: 'number', step: '0.01'},
        {campo: 'observacao', label: 'Observação', tipo: 'text'},
      ],
    }),

    criarEditorTabela({
      containerId: 'precos-taxas-regionais', endpoint: 'taxas-regionais',
      titulo: 'Taxa Fluvial (RCA) — só cobrada se origem OU destino for a cidade',
      // Sem campoMultiplo aqui de propósito (mesma mudança feita em Coleta
      // com Preço Fixo): vírgula não cria mais uma linha por cidade, uma
      // linha só cobre várias cidades com o mesmo valor.
      colunas: [
        {campo: 'cidade', label: 'Cidade(s) — separe por vírgula', tipo: 'text'},
        {campo: 'nome', label: 'Nome da taxa', tipo: 'text'},
        {campo: 'tipo', label: 'Tipo', tipo: 'select', opcoes: ['fixo', 'percentual']},
        {campo: 'valor', label: 'Valor (R$ ou %)', tipo: 'number', step: '0.01'},
        {campo: 'observacao', label: 'Observação', tipo: 'text'},
      ],
    }),

    criarEditorTabela({
      containerId: 'precos-transportadoras-terceirizadas', endpoint: 'transportadoras-terceirizadas',
      titulo: 'Transportadoras Terceirizadas (coleta/entrega)',
      colunas: [
        {campo: 'nome', label: 'Nome da transportadora', tipo: 'text'},
        {campo: 'cidade', label: 'Cidade atendida', tipo: 'text'},
        {campo: 'tipo', label: 'Tipo', tipo: 'select', opcoes: ['coleta', 'entrega', 'ambos']},
        {campo: 'valor', label: 'Valor combinado (R$)', tipo: 'moeda'},
        {campo: 'observacao', label: 'Observação', tipo: 'text'},
      ],
    }),

    criarEditorTabela({
      containerId: 'precos-faixas-coleta', endpoint: 'faixas-coleta', titulo: 'Faixas de Coleta por km (cidades sem preço fixo)',
      colunas: [
        {campo: 'de', label: 'De (km)', tipo: 'number'},
        {campo: 'ate', label: 'Até (km)', tipo: 'number'},
        {campo: 'taxa_fixa', label: 'Taxa fixa (R$)', tipo: 'moeda'},
        {campo: 'tarifa_km', label: 'Tarifa/km (R$)', tipo: 'moeda'},
        {campo: 'observacao', label: 'Observação', tipo: 'text'},
      ],
    }),

    criarEditorTabela({
      containerId: 'precos-faixas-peso-fracionado', endpoint: 'faixas-peso-fracionado',
      titulo: 'Faixas de Peso (Fracionado) — frete base = tarifa base + custo/kg acima do "De"',
      colunas: [
        {campo: 'de', label: 'De (kg)', tipo: 'number', step: '1'},
        {campo: 'ate', label: 'Até (kg)', tipo: 'number', step: '1'},
        {campo: 'tarifa_base', label: 'Tarifa base (R$)', tipo: 'moeda'},
        {campo: 'custo_kg_adicional', label: 'Custo/kg adicional (R$)', tipo: 'moeda'},
        {campo: 'observacao', label: 'Observação', tipo: 'text'},
      ],
    }),

    criarEditorTabela({
      containerId: 'precos-faixas-distancia-fracionado', endpoint: 'faixas-distancia-fracionado',
      titulo: 'Faixas de Distância (Fracionado) — frete base = taxa fixa + tarifa/km × distância',
      colunas: [
        {campo: 'de', label: 'De (km)', tipo: 'number', step: '1'},
        {campo: 'ate', label: 'Até (km)', tipo: 'number', step: '1'},
        {campo: 'taxa_fixa', label: 'Taxa fixa (R$)', tipo: 'moeda'},
        {campo: 'tarifa_km', label: 'Tarifa/km (R$)', tipo: 'moeda'},
        {campo: 'observacao', label: 'Observação', tipo: 'text'},
      ],
    }),

    criarEditorTabela({
      containerId: 'precos-categorias', endpoint: 'categorias', titulo: 'Categorias de Produto',
      colunas: [
        {campo: 'nome', label: 'Nome', tipo: 'text'},
        {campo: 'multiplicador', label: 'Multiplicador', tipo: 'number', step: '0.01'},
        {campo: 'observacao', label: 'Observação', tipo: 'text'},
      ],
    }),

    criarEditorTabela({
      containerId: 'precos-transportes', endpoint: 'transportes', titulo: 'Métodos de Transporte',
      colunas: [
        {campo: 'nome', label: 'Nome', tipo: 'text'},
        {campo: 'multiplicador', label: 'Multiplicador', tipo: 'number', step: '0.01'},
        {campo: 'fator_cubagem', label: 'Fator de cubagem', tipo: 'number', step: '1'},
        {campo: 'observacao', label: 'Observação', tipo: 'text'},
      ],
    }),

    criarEditorTabela({
      containerId: 'precos-slas', endpoint: 'slas', titulo: 'Níveis de Serviço (SLA)',
      colunas: [
        {campo: 'nome', label: 'Nome', tipo: 'text'},
        {campo: 'multiplicador', label: 'Multiplicador', tipo: 'number', step: '0.01'},
        {campo: 'prazo_dias', label: 'Prazo (dias)', tipo: 'number', step: '1'},
        {campo: 'observacao', label: 'Observação', tipo: 'text'},
      ],
    }),
  ]);

  const [filiaisParaColeta, veiculosParaColeta, pracasParaPedagio] = await filiaisVeiculosPromise;

  // Estas dependem das opções de filial/veículo acima pros <select> das
  // colunas -- rodam em paralelo entre si também.
  await Promise.all([
    criarEditorTabela({
      containerId: 'precos-faixas-km-veiculo', endpoint: 'faixas-km-veiculo',
      titulo: 'Faixas de KM por Veículo (R$/km escalonado por distância — substitui a tarifa fixa do veículo quando cadastrada)',
      colunas: [
        {campo: 'veiculo', label: 'Veículo', tipo: 'select', opcoes: veiculosParaColeta.map(v => v.nome)},
        {campo: 'de', label: 'De (km)', tipo: 'number', step: '1'},
        {campo: 'ate', label: 'Até (km)', tipo: 'number', step: '1'},
        {campo: 'tarifa_km', label: 'Tarifa/km (R$)', tipo: 'moeda'},
        {campo: 'observacao', label: 'Observação', tipo: 'text'},
      ],
    }),

    criarEditorTabela({
      containerId: 'precos-coleta-cidades-fixas', endpoint: 'coleta-cidades-fixas',
      titulo: 'Coleta com Preço Fixo por Cidade (rota filial de origem → cidade(s) do cliente + veículo)',
      // Sem campoMultiplo aqui de propósito: nessa tabela vírgula NÃO cria
      // uma linha por cidade (como em Taxas Regionais) — uma linha só cobre
      // várias cidades ao mesmo tempo, todas com o mesmo preço fixo.
      colunas: [
        {campo: 'filial_origem', label: 'Filial de origem (de onde o veículo sai)', tipo: 'select', opcoes: filiaisParaColeta.map(f => f.nome)},
        {campo: 'cidade_destino', label: 'Cidade(s) do cliente — separe por vírgula', tipo: 'text'},
        {campo: 'veiculo', label: 'Veículo', tipo: 'select', opcoes: veiculosParaColeta.map(v => v.nome)},
        {campo: 'valor_fixo', label: 'Valor fixo de coleta (R$)', tipo: 'moeda'},
        {campo: 'observacao', label: 'Observação', tipo: 'text'},
      ],
    }),

    criarEditorTabela({
      containerId: 'precos-taxas-balsa', endpoint: 'taxas-balsa',
      titulo: 'Taxa de Balsa',
      colunas: [
        {campo: 'cidade_origem', label: 'Cidade de origem (ou "*")', tipo: 'text'},
        {campo: 'cidade_destino', label: 'Cidade de destino (ou "*")', tipo: 'text'},
        {campo: 'veiculo', label: 'Veículo (ou "*")', tipo: 'select', opcoes: ['*', ...veiculosParaColeta.map(v => v.nome)]},
        {campo: 'tipo', label: 'Tipo', tipo: 'select', opcoes: ['fixo', 'percentual']},
        {campo: 'valor', label: 'Valor (R$ ou %)', tipo: 'number', step: '0.01'},
        {campo: 'observacao', label: 'Observação', tipo: 'text'},
      ],
    }),

    criarEditorTabela({
      containerId: 'precos-prioridades-rota', endpoint: 'prioridades-rota',
      titulo: 'Prioridade de rota',
      colunas: [
        {campo: 'estado_origem', label: 'Estado de origem (UF, ou "*")', tipo: 'select', opcoes: ['*', ...UFS_BRASIL]},
        {campo: 'cidade_destino', label: 'Cidade de destino (ou "*")', tipo: 'text'},
        {campo: 'filial_escala', label: 'Filial obrigatória de passagem', tipo: 'select', opcoes: filiaisParaColeta.map(f => f.nome)},
        {campo: 'observacao', label: 'Observação', tipo: 'text'},
      ],
    }),

    criarEditorTabela({
      containerId: 'precos-aliquotas-icms', endpoint: 'aliquotas-icms',
      titulo: 'ICMS por Rota (UF de origem → UF de destino — aplicado "por dentro"/gross-up sobre o frete total)',
      colunas: [
        {campo: 'estado_origem', label: 'UF de origem (ou "*")', tipo: 'select', opcoes: ['*', ...UFS_BRASIL]},
        {campo: 'estado_destino', label: 'UF de destino (ou "*")', tipo: 'select', opcoes: ['*', ...UFS_BRASIL]},
        {campo: 'aliquota', label: 'Alíquota (%)', tipo: 'number', step: '0.01'},
        {campo: 'observacao', label: 'Observação', tipo: 'text'},
      ],
    }),

    criarEditorTabela({
      containerId: 'precos-taxas-diaria-veiculo', endpoint: 'taxas-diaria-veiculo',
      titulo: 'Diária de Carreta e Cavalo por UF — cobrada uma vez quando há retirada OU entrega no cliente com frota própria nesse estado',
      colunas: [
        {campo: 'uf', label: 'UF', tipo: 'select', opcoes: UFS_BRASIL},
        {campo: 'valor_carreta', label: 'Diária da carreta (R$)', tipo: 'moeda'},
        {campo: 'valor_cavalo', label: 'Diária do cavalo (R$)', tipo: 'moeda'},
        {campo: 'observacao', label: 'Observação', tipo: 'text'},
      ],
    }),

    criarEditorTabela({
      containerId: 'precos-pedagios-rota', endpoint: 'pedagios-rota',
      titulo: 'Pedágios por Rota (praças que cada corredor atravessa — o valor final soma todas)',
      colunas: [
        {campo: 'cidade_origem', label: 'Cidade de origem (ou "*")', tipo: 'text'},
        {campo: 'cidade_destino', label: 'Cidade de destino (ou "*")', tipo: 'text'},
        {
          campo: 'praca_id', label: 'Praça de pedágio', tipo: 'select', numerico: true,
          opcoes: pracasParaPedagio.map(p => ({value: p.id, label: `${p.rodovia} — ${p.nome}`})),
        },
        {campo: 'observacao', label: 'Observação', tipo: 'text'},
      ],
    }),

    criarEditorTabela({
      containerId: 'precos-distancias-fixas', endpoint: 'distancias-fixas',
      titulo: 'Distâncias Fixas por Corredor (sobrepõe o cálculo automático de rota)',
      colunas: [
        {campo: 'cidade_origem', label: 'Cidade de origem (ou "*")', tipo: 'text'},
        {campo: 'cidade_destino', label: 'Cidade de destino (ou "*")', tipo: 'text'},
        {campo: 'distancia_km', label: 'Distância (km)', tipo: 'number', step: '1'},
        {campo: 'observacao', label: 'Observação', tipo: 'text'},
      ],
    }),
  ]);
}
