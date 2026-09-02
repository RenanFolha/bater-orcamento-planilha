const API_BASE = ""; // mesma origem (servido pelo próprio FastAPI)

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
  {chave: 'frete_base', rotulo: 'Frete base (custo/km + custo peso excedente)', tipo: 'brl'},

  {header: 'Multiplicadores'},
  {chave: 'multiplicador_categoria', rotulo: 'Multiplicador da categoria', tipo: 'mult'},
  {chave: 'multiplicador_transporte', rotulo: 'Multiplicador do transporte', tipo: 'mult'},
  {chave: 'multiplicador_sla', rotulo: 'Multiplicador do SLA', tipo: 'mult'},
  {chave: 'frete_ajustado', rotulo: 'Frete ajustado (base × multiplicadores)', tipo: 'brl'},

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
  {chave: 'tarifa_km_manutencao', rotulo: 'Tarifa de manutenção por km', tipo: 'brl'},
  {chave: 'distancia_manutencao_km', rotulo: 'Distância considerada na manutenção (ida + coleta própria + retorno)', tipo: 'km'},
  {chave: 'custo_manutencao', rotulo: 'Custo de manutenção', tipo: 'brl'},
  {chave: 'tarifa_km_retorno', rotulo: 'Tarifa de retorno vazio por km', tipo: 'brl'},
  {chave: 'distancia_retorno_km', rotulo: 'Distância de retorno vazio', tipo: 'km'},
  {chave: 'custo_retorno', rotulo: 'Custo de retorno vazio', tipo: 'brl'},

  {header: 'Taxas'},
  {chave: 'taxas_adicionais', rotulo: 'Taxas adicionais aplicadas', tipo: 'lista_taxa'},
  {chave: 'custo_taxas_adicionais', rotulo: 'Total de taxas adicionais', tipo: 'brl'},
  {chave: 'taxas_regionais', rotulo: 'Taxas regionais aplicadas', tipo: 'lista_taxa_regional'},
  {chave: 'custo_taxas_regionais', rotulo: 'Total de taxas regionais', tipo: 'brl'},
  {chave: 'taxa_balsa', rotulo: 'Taxa de balsa aplicada', tipo: 'balsa'},
  {chave: 'balsa_outro_veiculo', rotulo: 'Taxa de balsa cadastrada só p/ outro veículo', tipo: 'lista_veiculos'},
  {chave: 'custo_balsa', rotulo: 'Custo de balsa', tipo: 'brl'},

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
    case 'lista_veiculos':
      return (v && v.length) ? v.join(', ') : '—';
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
    const valor = _formatarValorMemoria(fonte[item.chave], item.tipo);
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
function pesoParaNumero(str){
  if(str == null || str === '') return 0;
  const limpo = String(str).replace(/\./g, '').replace(',', '.');
  const n = parseFloat(limpo);
  return isNaN(n) ? 0 : n;
}

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

async function inicializarFormulario(){
  let carregouParametros = false;
  btn.disabled = true;
  btn.textContent = 'Carregando...';
  statusTag.textContent = 'Conectando';
  try{
    await Promise.all([
      carregarOpcoes('categorias', document.getElementById('categoria')),
      carregarOpcoes('transportes', document.getElementById('transporte')),
      carregarOpcoes('slas', document.getElementById('sla')),
      carregarFiliais(),
      carregarTransportadoras(),
      carregarTransportesCache(),
    ]);
    carregouParametros = true;
    statusTag.textContent = 'Aguardando';
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

async function carregarTransportesCache(){
  const res = await fetch(`${API_BASE}/parametros/transportes`);
  if(!res.ok) throw new Error(`Erro HTTP ${res.status}`);
  transportesCache = await res.json();
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

// Caminho inverso: cliente só passou a cubagem (volume em m³) — a
// gente preenche Comprimento/Largura/Altura sozinho, assumindo uma caixa
// cúbica (lados iguais). Isso não muda o valor do frete: o cálculo só
// usa o produto comprimento×largura×altura, então qualquer combinação
// de dimensões que dê o mesmo volume chega no mesmo resultado — só
// precisamos preencher os 3 campos porque o formulário pede eles.
function aplicarCubagemManual(){
  const input = document.getElementById('cubagem-manual');
  const volumeM3 = parseFloat(input.value);
  if(!volumeM3 || volumeM3 <= 0) return;

  const volumeCm3 = volumeM3 * 1000000;
  const lado = Math.cbrt(volumeCm3);
  document.getElementById('comprimento').value = lado.toFixed(2);
  document.getElementById('largura').value = lado.toFixed(2);
  document.getElementById('altura').value = lado.toFixed(2);
  atualizarCubagem();
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
});

function resetarRetornoVazio(){
  distanciaRetornoInput.value = 0;
  destinoRetornoWrap.style.display = 'none';
  destinoRetornoFilialSel.value = '';
  destinoRetornoInfo.textContent = '';
  destinoEfetivoEnderecoResolvido = '';
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
});

configurarToggle('seg-origem-modo', (valor) => {
  origemModo = valor;
  origemTerceirizadaWrap.style.display = valor === 'terceirizada' ? '' : 'none';
  campoColeta.style.display = (origemTipo === 'retirada' && valor === 'propria') ? '' : 'none';
});

configurarToggle('seg-destino-modo', (valor) => {
  destinoModo = valor;
  destinoTerceirizadaWrap.style.display = valor === 'terceirizada' ? '' : 'none';
  resetarRetornoVazio();
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

btnGeo.addEventListener('click', async () => {
  geoStatus.className = 'geo-status';
  geoStatus.textContent = '';
  cidadeColetaResolvida = '';
  cidadeOrigemResolvida = '';
  cidadeDestinoResolvida = '';

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
    const horas = Math.floor(data2.duracao_min / 60);
    const minutos = Math.round(data2.duracao_min % 60);
    const tempoTexto = horas > 0 ? `${horas}h${minutos.toString().padStart(2,'0')}` : `${minutos} min`;

    let mensagemPedagio = '';
    if(typeof data2.pedagio_valor === 'number'){
      pedagioInput.value = formatarValorMoeda(data2.pedagio_valor);
      campoPedagio.style.display = '';
      mensagemPedagio = ` Pedágio estimado: ${fmtBRL(data2.pedagio_valor)}.`;
    }else{
      campoPedagio.style.display = 'none';
      pedagioInput.value = formatarValorMoeda(0);
    }

    geoStatus.classList.add('ok');
    geoStatus.textContent = `${mensagemColeta}Distância do frete: ${data2.distancia_km} km (≈ ${tempoTexto}).${mensagemPedagio} Campos preenchidos — edite se precisar.`;

  }catch(err){
    geoStatus.classList.add('err');
    geoStatus.textContent = `${err.message} Você pode digitar as distâncias manualmente nos campos abaixo.`;
  }finally{
    btnGeo.disabled = false;
    btnGeo.textContent = 'Calcular distância';
  }
});

form.addEventListener('submit', async (ev) => {
  ev.preventDefault();
  errorBox.classList.remove('show');
  errorBox.textContent = '';
  stamp.classList.remove('show');
  ultimoOrcamento = null;
  document.getElementById('historico-salvar-status').textContent = '';

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
    pedagio: valorMoedaParaNumero(pedagioInput.value),
    cidade_coleta: cidadeColetaResolvida,
    cidade_origem: cidadeOrigemResolvida,
    cidade_destino: cidadeDestinoResolvida,
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

    document.getElementById('d-custo-km').textContent = fmtBRL(calc.custo_km);
    document.getElementById('d-peso-exc').textContent = `${calc.peso_excedente_kg} kg`;
    document.getElementById('d-custo-peso-exc').textContent = fmtBRL(calc.custo_peso_excedente);
    document.getElementById('d-base').textContent = fmtBRL(calc.frete_base);
    document.getElementById('d-mult').textContent =
      `${fmtMult(calc.multiplicador_categoria)} × ${fmtMult(calc.multiplicador_transporte)} × ${fmtMult(calc.multiplicador_sla)}`;
    document.getElementById('d-ajustado').textContent = fmtBRL(calc.frete_ajustado);

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
      document.getElementById('d-retorno').textContent =
        `${fmtBRL(calc.custo_retorno)} (${calc.distancia_retorno_km} km vazio)`;
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
    if(calc.custo_balsa > 0 && calc.taxa_balsa){
      document.getElementById('d-taxa-balsa').textContent = fmtBRL(calc.custo_balsa);
      linhaTaxaBalsa.title = `${calc.taxa_balsa.cidade_origem} → ${calc.taxa_balsa.cidade_destino} (${calc.taxa_balsa.veiculo})`;
      linhaTaxaBalsa.style.display = 'flex';
    }else{
      linhaTaxaBalsa.style.display = 'none';
    }

    const linhaTaxas = document.getElementById('linha-taxas');
    const blocoDetalheTaxas = document.getElementById('bloco-detalhe-taxas');
    if(calc.custo_taxas_adicionais > 0){
      document.getElementById('d-taxas').textContent = fmtBRL(calc.custo_taxas_adicionais);
      linhaTaxas.style.display = 'flex';
      const listaDetalhe = document.getElementById('lista-detalhe-taxas');
      listaDetalhe.innerHTML = calc.taxas_adicionais.map(t => {
        const rotulo = t.tipo === 'percentual' ? `${esc(t.nome)} (${t.valor_configurado}%)` : esc(t.nome);
        return `<div class="line"><span>${rotulo}</span><span>${fmtBRL(t.valor_aplicado)}</span></div>`;
      }).join('');
      blocoDetalheTaxas.style.display = 'block';
    }else{
      linhaTaxas.style.display = 'none';
      blocoDetalheTaxas.style.display = 'none';
    }

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

document.getElementById('btn-toggle-memoria').addEventListener('click', () => {
  const bloco = document.getElementById('bloco-memoria-calculo');
  const label = document.getElementById('btn-toggle-memoria-label');
  const abrindo = bloco.style.display === 'none';
  bloco.style.display = abrindo ? '' : 'none';
  label.textContent = abrindo ? 'Esconder todas as variáveis do cálculo' : 'Ver todas as variáveis do cálculo';
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
// Navegação entre views (Novo Orçamento / Tabela de Preços / etc.)
// ============================================================

const views = {
  orcamento: document.getElementById('view-orcamento'),
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

  if(viewName === 'precos') carregarTabelaPrecos();
  if(viewName === 'historico') carregarHistorico();
  if(viewName === 'config') carregarConfiguracoes();
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
  // (ex: fez logout com "Histórico" aberto), volta pro Novo Orçamento.
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

  function mostrarStatus(msg, ok){
    statusEl.textContent = msg;
    statusEl.className = 'precos-status ' + (ok ? 'ok' : 'err');
    if(ok) setTimeout(() => { statusEl.textContent = ''; statusEl.className = 'precos-status'; }, 3000);
  }

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

  function mostrarStatus(msg, ok){
    statusEl.textContent = msg;
    statusEl.className = 'precos-status ' + (ok ? 'ok' : 'err');
    if(ok){
      setTimeout(() => { statusEl.textContent = ''; statusEl.className = 'precos-status'; }, 3000);
    }
  }

  function criarInputs(dados = {}, opts = {}){
    return colunas.map(c => {
      if(c.tipo === 'select'){
        const select = document.createElement('select');
        c.opcoes.forEach(op => {
          const option = document.createElement('option');
          option.value = op;
          option.textContent = op;
          select.appendChild(option);
        });
        select.value = dados[c.campo] ?? c.opcoes[0];
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
      if(c.tipo === 'select' || c.tipo === 'text'){
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
    countTag.textContent = `${itens.length} linha${itens.length === 1 ? '' : 's'}`;

    itens.forEach(item => {
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
      });

      const btnExcluir = criarElemento('button', {type: 'button', class: 'btn-icone excluir'}, '🗑 Excluir');
      btnExcluir.addEventListener('click', async () => {
        if(!confirm('Excluir esta linha? Essa ação não pode ser desfeita.')) return;
        try{
          const res = await fetch(`${API_BASE}/admin/${endpoint}/${item.id}`, {method: 'DELETE'});
          if(!res.ok){
            const data = await res.json();
            throw new Error(data.detail || 'Erro ao excluir.');
          }
          await carregar();
          mostrarStatus('Linha excluída.', true);
        }catch(e){ mostrarStatus(e.message, false); }
      });

      tdAcoes.appendChild(btnSalvar);
      tdAcoes.appendChild(btnExcluir);
      tr.appendChild(tdAcoes);
      tbody.appendChild(tr);
    });

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
            sucesso.push(campoMultiplo ? item[campoMultiplo] : '');
          }catch(e){
            falhas.push(`${campoMultiplo ? item[campoMultiplo] : ''}: ${e.message}`.trim());
          }
        }

        await carregar();
        if(falhas.length === 0){
          mostrarStatus(alvos.length > 1 ? `${sucesso.length} linhas adicionadas.` : 'Linha adicionada.', true);
        }else if(sucesso.length === 0){
          mostrarStatus(`Nada adicionado — ${falhas.join(' | ')}`, false);
        }else{
          mostrarStatus(`${sucesso.length} adicionada(s). Falharam: ${falhas.join(' | ')}`, false);
        }
      }catch(e){ mostrarStatus(e.message, false); }
    });
    tdAcoesNova.appendChild(btnAdd);
    trNova.appendChild(tdAcoesNova);
    tbody.appendChild(trNova);
  }

  await carregar();
}

let precosCarregado = false;

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
    renderizarHistorico(historicoCache);
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
      try{
        const res = await fetch(`${API_BASE}/historico/${btn.dataset.id}`, {method: 'DELETE'});
        if(!res.ok) throw new Error(`Erro HTTP ${res.status}`);
        await carregarHistorico();
      }catch(e){
        alert(`Erro ao excluir: ${e.message}`);
      }
    });
  });
}

document.getElementById('historico-busca').addEventListener('input', (ev) => {
  const termo = ev.target.value.trim().toLowerCase();
  if(!termo){ renderizarHistorico(historicoCache); return; }
  const filtrado = historicoCache.filter(o =>
    (o.cliente || '').toLowerCase().includes(termo) ||
    (o.codigo || '').toLowerCase().includes(termo) ||
    (o.responsavel || '').toLowerCase().includes(termo)
  );
  renderizarHistorico(filtrado);
});

let detalheHistoricoCodigo = null;

async function abrirDetalheHistorico(codigo){
  try{
    const res = await fetch(`${API_BASE}/historico/${codigo}`);
    if(!res.ok) throw new Error(`Erro HTTP ${res.status}`);
    const registro = await res.json();
    detalheHistoricoCodigo = registro.codigo;
    const calc = registro.dados?.resultado?.calculos_intermediarios || {};
    const entrada = registro.dados?.resultado?.entrada || {};

    document.getElementById('detalhe-titulo').textContent = `${registro.codigo} — ${registro.cliente}`;
    document.getElementById('detalhe-subtitulo').textContent =
      `Responsável: ${registro.responsavel} · ${new Date(registro.criado_em).toLocaleString('pt-BR')}`;

    const linhas = [
      ['Rota', [registro.origem_resumo, registro.destino_resumo].filter(Boolean).join(' → ') || '—'],
      ['Veículo', registro.veiculo || entrada.veiculo || '—'],
      ['Distância', `${registro.distancia_km} km`],
      ['Peso considerado', calc.peso_considerado_kg != null ? `${calc.peso_considerado_kg} kg` : '—'],
      ['Valor da mercadoria', fmtBRL(registro.valor_mercadoria)],
      ['Frete total', fmtBRL(registro.frete_total)],
    ];
    document.getElementById('detalhe-conteudo').innerHTML = linhas.map(([label, valor]) => `
      <div class="line"><span>${esc(label)}</span><span>${esc(valor)}</span></div>
    `).join('');

    renderizarMemoriaCalculo(registro.dados?.resultado, 'detalhe-memoria-calculo', false);

    document.getElementById('view-historico').style.display = 'none';
    document.getElementById('view-historico-detalhe').style.display = 'block';
  }catch(e){
    alert(`Erro ao abrir o orçamento: ${e.message}`);
  }
}

document.getElementById('btn-voltar-historico').addEventListener('click', () => {
  document.getElementById('view-historico-detalhe').style.display = 'none';
  document.getElementById('view-historico').style.display = 'block';
});

document.getElementById('btn-exportar-planilha').addEventListener('click', async (ev) => {
  if(!detalheHistoricoCodigo) return;
  const btn = ev.currentTarget;
  const textoOriginal = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = 'Gerando...';
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
    alert(`Erro ao exportar planilha: ${e.message}`);
  }finally{
    btn.disabled = false;
    btn.innerHTML = textoOriginal;
  }
});

async function carregarTabelaPrecos(){
  if(precosCarregado) return;
  precosCarregado = true;

  await criarEditorTabela({
    containerId: 'precos-filiais', endpoint: 'filiais',
    titulo: 'Filiais (editar o endereço já força nova geocodificação)',
    colunas: [
      {campo: 'nome', label: 'Nome (usado como cidade de referência)', tipo: 'text'},
      {campo: 'endereco', label: 'Endereço completo (rua, número, bairro, cidade, UF, CEP)', tipo: 'text'},
    ],
  });

  await criarEditorTabela({
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
      {campo: 'observacao', label: 'Observação', tipo: 'text'},
    ],
  });

  await criarEditorTabela({
    containerId: 'precos-taxas-adicionais', endpoint: 'taxas-adicionais', titulo: 'Taxas Adicionais',
    colunas: [
      {campo: 'nome', label: 'Nome', tipo: 'text'},
      {campo: 'tipo', label: 'Tipo', tipo: 'select', opcoes: ['fixo', 'percentual']},
      {campo: 'valor', label: 'Valor (R$ se fixo, % se percentual)', tipo: 'number', step: '0.01'},
      {campo: 'observacao', label: 'Observação', tipo: 'text'},
    ],
  });

  const [filiaisParaColeta, veiculosParaColeta] = await Promise.all([
    fetch(`${API_BASE}/admin/filiais`).then(r => r.json()).catch(() => []),
    fetch(`${API_BASE}/admin/veiculos`).then(r => r.json()).catch(() => []),
  ]);

  await criarEditorTabela({
    containerId: 'precos-faixas-km-veiculo', endpoint: 'faixas-km-veiculo',
    titulo: 'Faixas de KM por Veículo (R$/km escalonado por distância — substitui a tarifa fixa do veículo quando cadastrada)',
    colunas: [
      {campo: 'veiculo', label: 'Veículo', tipo: 'select', opcoes: veiculosParaColeta.map(v => v.nome)},
      {campo: 'de', label: 'De (km)', tipo: 'number', step: '1'},
      {campo: 'ate', label: 'Até (km)', tipo: 'number', step: '1'},
      {campo: 'tarifa_km', label: 'Tarifa/km (R$)', tipo: 'moeda'},
      {campo: 'observacao', label: 'Observação', tipo: 'text'},
    ],
  });

  await criarEditorTabela({
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
  });

  await criarEditorTabela({
    containerId: 'precos-taxas-regionais', endpoint: 'taxas-regionais',
    titulo: 'Taxas Regionais (só cobradas se origem OU destino for a cidade)',
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
  });

  await criarEditorTabela({
    containerId: 'precos-taxas-balsa', endpoint: 'taxas-balsa',
    titulo: 'Taxas de Balsa (travessia origem → destino, direcional — ida e volta podem ter valores diferentes)',
    colunas: [
      {campo: 'cidade_origem', label: 'Cidade de origem', tipo: 'text'},
      {campo: 'cidade_destino', label: 'Cidade de destino', tipo: 'text'},
      {campo: 'veiculo', label: 'Veículo', tipo: 'select', opcoes: veiculosParaColeta.map(v => v.nome)},
      {campo: 'tipo', label: 'Tipo', tipo: 'select', opcoes: ['fixo', 'percentual']},
      {campo: 'valor', label: 'Valor (R$ ou %)', tipo: 'number', step: '0.01'},
      {campo: 'observacao', label: 'Observação', tipo: 'text'},
    ],
  });

  await criarEditorTabela({
    containerId: 'precos-transportadoras-terceirizadas', endpoint: 'transportadoras-terceirizadas',
    titulo: 'Transportadoras Terceirizadas (coleta/entrega)',
    colunas: [
      {campo: 'nome', label: 'Nome da transportadora', tipo: 'text'},
      {campo: 'cidade', label: 'Cidade atendida', tipo: 'text'},
      {campo: 'tipo', label: 'Tipo', tipo: 'select', opcoes: ['coleta', 'entrega', 'ambos']},
      {campo: 'valor', label: 'Valor combinado (R$)', tipo: 'moeda'},
      {campo: 'observacao', label: 'Observação', tipo: 'text'},
    ],
  });

  await criarEditorTabela({
    containerId: 'precos-faixas-coleta', endpoint: 'faixas-coleta', titulo: 'Faixas de Coleta por km (cidades sem preço fixo)',
    colunas: [
      {campo: 'de', label: 'De (km)', tipo: 'number'},
      {campo: 'ate', label: 'Até (km)', tipo: 'number'},
      {campo: 'taxa_fixa', label: 'Taxa fixa (R$)', tipo: 'moeda'},
      {campo: 'tarifa_km', label: 'Tarifa/km (R$)', tipo: 'moeda'},
      {campo: 'observacao', label: 'Observação', tipo: 'text'},
    ],
  });

  await criarEditorTabela({
    containerId: 'precos-categorias', endpoint: 'categorias', titulo: 'Categorias de Produto',
    colunas: [
      {campo: 'nome', label: 'Nome', tipo: 'text'},
      {campo: 'multiplicador', label: 'Multiplicador', tipo: 'number', step: '0.01'},
      {campo: 'observacao', label: 'Observação', tipo: 'text'},
    ],
  });

  await criarEditorTabela({
    containerId: 'precos-transportes', endpoint: 'transportes', titulo: 'Métodos de Transporte',
    colunas: [
      {campo: 'nome', label: 'Nome', tipo: 'text'},
      {campo: 'multiplicador', label: 'Multiplicador', tipo: 'number', step: '0.01'},
      {campo: 'fator_cubagem', label: 'Fator de cubagem', tipo: 'number', step: '1'},
      {campo: 'observacao', label: 'Observação', tipo: 'text'},
    ],
  });

  await criarEditorTabela({
    containerId: 'precos-slas', endpoint: 'slas', titulo: 'Níveis de Serviço (SLA)',
    colunas: [
      {campo: 'nome', label: 'Nome', tipo: 'text'},
      {campo: 'multiplicador', label: 'Multiplicador', tipo: 'number', step: '0.01'},
      {campo: 'prazo_dias', label: 'Prazo (dias)', tipo: 'number', step: '1'},
      {campo: 'observacao', label: 'Observação', tipo: 'text'},
    ],
  });
}
