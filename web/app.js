const form = document.querySelector('#upload-form');
const input = document.querySelector('#file-input');
const dropzone = document.querySelector('#dropzone');
const fileLabel = document.querySelector('#file-label');
const errorMessage = document.querySelector('#error-message');
const loadingMessage = document.querySelector('#loading-message');
const button = document.querySelector('#process-button');
const progressBar = document.querySelector('#progress-bar');
const progressValue = document.querySelector('#progress-value');
const progressLabel = document.querySelector('#progress-label');
const progressDetail = document.querySelector('#progress-detail');
const alertsPanel = document.querySelector('#alerts-panel');
const alertsList = document.querySelector('#alerts-list');
const alertsToggle = document.querySelector('#alerts-toggle');
const descartesPanel = document.querySelector('#descartes-panel');
const descartesBody = document.querySelector('#descartes-body');
const descartesHead = document.querySelector('#descartes-head');
const descartesCount = document.querySelector('#descartes-count');
const themeToggle = document.querySelector('#theme-toggle');
const buildStatus = document.querySelector('#build-status');
const diagnosticPanel = document.querySelector('#error-diagnostic');
let progressTimer;

fetch(`/api/health?cache=${Date.now()}`, { cache: 'no-store' })
  .then(response => response.ok ? response.json() : Promise.reject(new Error('health check failed')))
  .then(({ build }) => {
    if (build && build !== 'unknown') buildStatus.textContent = `Motor atualizado · ${build.slice(0, 8)}`;
  })
  .catch(() => { buildStatus.textContent = 'Motor operacional'; });

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const dark = theme === 'dark';
  themeToggle.textContent = dark ? '☀' : '☾';
  themeToggle.setAttribute('aria-label', dark ? 'Ativar tema claro' : 'Ativar tema escuro');
  themeToggle.title = dark ? 'Ativar tema claro' : 'Ativar tema escuro';
}

const savedTheme = localStorage.getItem('equalizador-theme');
const systemTheme = window.matchMedia('(prefers-color-scheme: dark)');
applyTheme(savedTheme === 'dark' || (!savedTheme && systemTheme.matches) ? 'dark' : 'light');
systemTheme.addEventListener('change', event => {
  if (!localStorage.getItem('equalizador-theme')) applyTheme(event.matches ? 'dark' : 'light');
});
themeToggle.addEventListener('click', () => {
  const nextTheme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  localStorage.setItem('equalizador-theme', nextTheme);
  applyTheme(nextTheme);
});

function setAlertsOpen(abrir) {
  // O atributo ``hidden`` é a única fonte de verdade do painel: sem removê-lo,
  // ``[hidden] { display: none !important; }`` venceria qualquer classe CSS.
  alertsToggle.setAttribute('aria-expanded', String(abrir));
  alertsToggle.innerHTML = abrir ? '&#128064;' : '&#128065;';
  alertsToggle.title = abrir ? 'Ocultar pontos de atenção' : 'Mostrar pontos de atenção';
  alertsList.hidden = !abrir;
  alertsList.setAttribute('aria-hidden', String(!abrir));
  alertsPanel.classList.toggle('collapsed', !abrir);
}
alertsToggle.addEventListener('click', () => {
  setAlertsOpen(alertsToggle.getAttribute('aria-expanded') !== 'true');
});

input.addEventListener('change', () => { if (input.files[0]) fileLabel.textContent = input.files[0].name; });
['dragenter', 'dragover'].forEach(event => dropzone.addEventListener(event, e => { e.preventDefault(); dropzone.classList.add('dragging'); }));
['dragleave', 'drop'].forEach(event => dropzone.addEventListener(event, e => { e.preventDefault(); dropzone.classList.remove('dragging'); }));
dropzone.addEventListener('drop', e => { if (e.dataTransfer.files[0]) { input.files = e.dataTransfer.files; fileLabel.textContent = input.files[0].name; } });

const number = value => value == null ? '-' : typeof value === 'number' ? value.toLocaleString('pt-BR', { maximumFractionDigits: 2 }) : value;
const currency = value => value == null ? '-' : Number(value).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', maximumFractionDigits: 0 });
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]));
const escapeSvg = value => String(value ?? '').replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' }[character]));
function chartMessage(container, message = 'Não há dados suficientes para este gráfico.') {
  container.innerHTML = `<div class="chart-empty">${escapeHtml(message)}</div>`;
}

function resetDiagnostic() {
  diagnosticPanel.hidden = true;
  document.querySelector('#diagnostic-missing').hidden = true;
  document.querySelector('#diagnostic-found').hidden = true;
  document.querySelector('#diagnostic-tips').hidden = true;
}

function resetProgress() {
  clearInterval(progressTimer);
  progressBar.classList.remove('processing');
  progressBar.style.width = '0%';
  progressValue.textContent = '0%';
  progressLabel.textContent = 'Preparando arquivo...';
  progressDetail.textContent = 'A análise será executada no servidor.';
}

function esconderLoading() {
  clearInterval(progressTimer);
  loadingMessage.hidden = true;
}

function renderList(containerId, blockId, items) {
  const list = document.querySelector(containerId);
  if (!items || !items.length) { document.querySelector(blockId).hidden = true; return; }
  list.innerHTML = items.map(item => `<li>${escapeHtml(item)}</li>`).join('');
  document.querySelector(blockId).hidden = false;
}

function renderDiagnostic(diagnostic) {
  if (!diagnostic || typeof diagnostic !== 'object') return false;
  document.querySelector('#diagnostic-title').textContent = diagnostic.titulo || 'Não foi possível ler a planilha';
  document.querySelector('#diagnostic-message').textContent = diagnostic.mensagem || '';
  renderList('#diagnostic-missing-list', '#diagnostic-missing', diagnostic.faltando);
  const encontrados = diagnostic.encontrado && typeof diagnostic.encontrado === 'object'
    ? Object.entries(diagnostic.encontrado).map(([conceito, coluna]) => `${conceito}: ${coluna}`)
    : [];
  renderList('#diagnostic-found-list', '#diagnostic-found', encontrados);
  renderList('#diagnostic-tips-list', '#diagnostic-tips', diagnostic.dicas);
  diagnosticPanel.hidden = false;
  return true;
}
function renderHorizontalChart(container, items, color, formatter, limit = 8) {
  if (!items.length) { chartMessage(container); return; }
  const visible = items.slice(0, limit);
  const max = Math.max(...visible.map(item => Number(item.value) || 0), 1);
  const width = 720;
  const rowHeight = 36;
  const labelWidth = 158;
  const valueWidth = 86;
  const barWidth = width - labelWidth - valueWidth;
  const height = visible.length * rowHeight + 10;
  const bars = visible.map((item, index) => {
    const y = index * rowHeight + 7;
    const amount = Math.max(3, ((Number(item.value) || 0) / max) * barWidth);
    return `<g class="chart-row"><title>${escapeSvg(item.label)}: ${escapeSvg(formatter(item.value))}</title><text x="0" y="${y + 16}" class="chart-label">${escapeSvg(item.label)}</text><rect x="${labelWidth}" y="${y + 3}" width="${barWidth}" height="18" rx="2" class="chart-track"/><rect x="${labelWidth}" y="${y + 3}" width="${amount}" height="18" rx="2" fill="${color}"/><text x="${width - valueWidth}" y="${y + 16}" class="chart-value">${escapeSvg(formatter(item.value))}</text></g>`;
  }).join('');
  container.innerHTML = `<svg class="chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMinYMin meet" aria-hidden="true">${bars}</svg>`;
}
function renderSpreadChart(container, rows) {
  const items = rows.filter(row => Number.isFinite(Number(row['Diferença %']))).sort((a, b) => Number(b['Diferença %']) - Number(a['Diferença %'])).slice(0, 8).map(row => ({
    label: `${row.ID} · ${(row['Descrição Solicitada'] || '').slice(0, 21)}`,
    value: Number(row['Diferença %']),
  }));
  renderHorizontalChart(container, items, 'var(--chart-red)', value => `${Number(value).toLocaleString('pt-BR', { maximumFractionDigits: 1 })}%`);
}
function renderDeliveryChart(container, rows) {
  const items = rows.map(row => ({
    label: row.Fornecedor,
    value: Number(row['Dias para Entrega']),
  })).filter(item => Number.isFinite(item.value)).sort((a, b) => a.value - b.value);
  renderColumnChart(container, items, 'var(--chart-cyan)', value => `${number(value)} dias`);
}
function renderColumnChart(container, items, color, formatter) {
  if (!items.length) { chartMessage(container); return; }
  const visible = items.slice(0, 8);
  const max = Math.max(...visible.map(item => item.value), 1);
  const width = 720;
  const height = 220;
  const chartBottom = 168;
  const columnWidth = 74;
  const gap = (width - visible.length * columnWidth) / (visible.length + 1);
  const columns = visible.map((item, index) => {
    const x = gap + index * (columnWidth + gap);
    const barHeight = Math.max(4, item.value / max * 122);
    const y = chartBottom - barHeight;
    return `<g class="chart-column"><title>${escapeSvg(item.label)}: ${escapeSvg(formatter(item.value))}</title><line x1="${x}" y1="${chartBottom}" x2="${x + columnWidth}" y2="${chartBottom}" class="chart-axis"/><rect x="${x + 8}" y="${y}" width="${columnWidth - 16}" height="${barHeight}" rx="2" fill="${color}"/><text x="${x + columnWidth / 2}" y="${y - 8}" text-anchor="middle" class="chart-column-value">${escapeSvg(formatter(item.value))}</text><text x="${x + columnWidth / 2}" y="${chartBottom + 20}" text-anchor="middle" class="chart-column-label">${escapeSvg(item.label)}</text></g>`;
  }).join('');
  container.innerHTML = `<svg class="chart-svg chart-svg-columns" viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMinYMin meet" aria-hidden="true">${columns}</svg>`;
}
function renderScenarioChart(container, table) {
  const fields = [
    ['BASELINE', 'Baseline'], ['BASELINE AJUSTADO', 'Baseline ajustado'],
    ['ESTUDO DOS MÍNIMOS', 'Estudo dos mínimos'], ['TARGET', 'Target'], ['VIVO FINAL', 'Vivo final'],
  ];
  const items = fields.map(([field, label]) => ({
    label, value: table.reduce((total, row) => total + (Number(row[field]) || 0) * (Number(row.Quantidade) || 1), 0),
  })).filter(item => item.value > 0);
  if (!items.length) { chartMessage(container); return; }
  const max = Math.max(...items.map(item => item.value), 1);
  const width = 720;
  const height = 220;
  const chartBottom = 170;
  const columnWidth = 92;
  const gap = (width - items.length * columnWidth) / (items.length + 1);
  const bars = items.map((item, index) => {
    const x = gap + index * (columnWidth + gap);
    const barHeight = Math.max(4, item.value / max * 122);
    const y = chartBottom - barHeight;
    return `<g class="chart-column"><title>${escapeSvg(item.label)}: ${escapeSvg(currency(item.value))}</title><line x1="${x}" y1="${chartBottom}" x2="${x + columnWidth}" y2="${chartBottom}" class="chart-axis"/><rect x="${x + 10}" y="${y}" width="${columnWidth - 20}" height="${barHeight}" rx="2" fill="var(--chart-cyan)"/><text x="${x + columnWidth / 2}" y="${y - 8}" text-anchor="middle" class="chart-column-value">${escapeSvg(currency(item.value))}</text><text x="${x + columnWidth / 2}" y="${chartBottom + 20}" text-anchor="middle" class="chart-column-label">${escapeSvg(item.label)}</text></g>`;
  }).join('');
  container.innerHTML = `<svg class="chart-svg chart-svg-columns" viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMinYMin meet" aria-hidden="true">${bars}</svg>`;
}
const CHART_CARDS = [
  { id: 'supplier-value-chart', title: 'Valor elegível por fornecedor', desc: 'Quanto custaria comprar todos os itens elegíveis de cada proposta.', key: 'R$', keyClass: 'blue-key', wide: true },
  { id: 'supplier-wins-chart', title: 'Participação nos menores preços', desc: 'Quantidade de itens em que cada fornecedor teve o menor valor.', key: 'itens', keyClass: 'yellow-key', wide: false },
  { id: 'spread-chart', title: 'Maior dispersão entre propostas', desc: 'Itens que merecem negociação ou validação comercial.', key: '%', keyClass: 'red-key', wide: false },
  { id: 'delivery-chart', title: 'Prazo de entrega por fornecedor', desc: 'Menor prazo melhora a pontuação comercial; entrega imediata aparece como zero dias.', key: 'dias', keyClass: 'cyan-key', wide: false },
  { id: 'scenario-chart', cardId: 'scenario-chart-card', title: 'Cenários da matriz de negociação', desc: 'Comparação ponderada pela quantidade dos itens.', key: 'R$', keyClass: 'cyan-key', wide: true },
];
function buildChartCards() {
  const grid = document.querySelector('#charts-grid');
  if (!grid || grid.dataset.ready) return;
  const template = document.querySelector('#chart-card-template');
  CHART_CARDS.forEach(config => {
    const node = template.content.firstElementChild.cloneNode(true);
    if (config.cardId) node.id = config.cardId;
    node.classList.toggle('chart-card-wide', Boolean(config.wide));
    node.querySelector('.chart-title').textContent = config.title;
    node.querySelector('.chart-desc').textContent = config.desc;
    const key = node.querySelector('.chart-key');
    key.textContent = config.key;
    key.classList.add(config.keyClass);
    const chart = node.querySelector('.chart');
    chart.id = config.id;
    chart.setAttribute('aria-label', config.title);
    chart.querySelector('.chart-fallback').textContent = `Sem dados suficientes para ${config.title.toLowerCase()}.`;
    grid.appendChild(node);
  });
  grid.dataset.ready = 'true';
}
function renderCharts(data) {
  buildChartCards();
  const summary = data.resumo_fornecedores || [];
  const chartPanel = document.querySelector('#charts-panel');
  chartPanel.hidden = false;
  renderHorizontalChart(
    document.querySelector('#supplier-value-chart'),
    summary.filter(row => Number(row['Total Proposta Elegível']) > 0).sort((a, b) => Number(a['Total Proposta Elegível']) - Number(b['Total Proposta Elegível'])).map(row => ({ label: row.Fornecedor, value: Number(row['Total Proposta Elegível']) })),
    'var(--chart-blue)', currency,
  );
  renderHorizontalChart(
    document.querySelector('#supplier-wins-chart'),
    summary.sort((a, b) => Number(b['Menores Preços'] || 0) - Number(a['Menores Preços'] || 0)).map(row => ({ label: row.Fornecedor, value: Number(row['Menores Preços'] || 0) })),
    'var(--chart-yellow)', value => `${number(value)} itens`,
  );
  renderSpreadChart(document.querySelector('#spread-chart'), data.mapa_comparativo || []);
  renderDeliveryChart(document.querySelector('#delivery-chart'), data.indicadores_comerciais || []);
  const matrix = data.referencia_matriz?.tabela || [];
  const scenarioCard = document.querySelector('#scenario-chart-card');
  scenarioCard.hidden = matrix.length === 0;
  if (matrix.length) renderScenarioChart(document.querySelector('#scenario-chart'), matrix);
}
function updateProgress(value, label, detail) {
  progressBar.style.width = `${value}%`;
  progressValue.textContent = `${value}%`;
  progressLabel.textContent = label;
  progressDetail.textContent = detail;
}
function startProgress() {
  let value = 8;
  const stages = [
    ['Lendo planilha...', 'Identificando abas e colunas.'],
    ['Normalizando dados...', 'Validando itens, quantidades e unidades.'],
    ['Calculando recomendações...', 'Comparando preços e condições comerciais.'],
  ];
  updateProgress(value, stages[0][0], stages[0][1]);
  progressTimer = setInterval(() => {
    if (value < 86) {
      value = Math.min(value + 3, 86);
      const stage = value < 32 ? stages[0] : value < 64 ? stages[1] : stages[2];
      updateProgress(value, stage[0], stage[1]);
      return;
    }
    progressBar.classList.add('processing');
    progressValue.textContent = '...';
    progressLabel.textContent = 'Finalizando análise...';
    progressDetail.textContent = 'O servidor está consolidando o relatório. Arquivos grandes podem levar alguns minutos.';
  }, 420);
}
function finishProgress() { clearInterval(progressTimer); progressBar.classList.remove('processing'); updateProgress(100, 'Análise concluída.', 'Preparando os resultados na tela.'); }
function renderTable(rows) {
  const columns = ['ID', 'Descrição', 'Fornecedor Recomendado', 'Valor Unitário', 'Score Recomendação', 'Empate Técnico'];
  const aliases = { 'Descrição': 'Descrição Cotada', 'Fornecedor Recomendado': 'Fornecedor Recomendado' };
  const head = document.querySelector('#recommendations-head');
  const body = document.querySelector('#recommendations-body');
  head.innerHTML = `<tr>${columns.map(c => `<th>${escapeHtml(c)}</th>`).join('')}</tr>`;
  body.innerHTML = rows.map(row => `<tr>${columns.map(column => {
    const key = aliases[column] || column;
    return `<td>${escapeHtml(number(row[key]))}</td>`;
  }).join('')}</tr>`).join('');
}
function renderSourceAnalysis(data) {
  const source = data.analise_fonte;
  if (!source || !source.perfil) return;
  const quality = source.perfil.qualidade || {};
  document.querySelector('#source-analysis').hidden = false;
  document.querySelector('#source-type').textContent = source.perfil.tipo || '';
  const metrics = ['Linhas físicas analisadas', 'Linhas válidas', 'Linhas descartadas', 'Produtos distintos', 'Fornecedores distintos', 'Linhas com preço', 'Linhas sem preço'];
  document.querySelector('#source-metrics').innerHTML = metrics.filter(label => quality[label] != null).map(label => `<div class="source-metric"><strong>${escapeHtml(number(quality[label]))}</strong><span>${escapeHtml(label)}</span></div>`).join('');
  const rows = (source.produtos || []).slice().sort((a, b) => (b.Cotações || 0) - (a.Cotações || 0)).slice(0, 20);
  const columns = ['Produto', 'Categoria', 'Cotações', 'Fornecedores', 'Menor Preço', 'Preço Médio', 'Maior Preço', 'Variação de Preço %'];
  document.querySelector('#source-products-head').innerHTML = `<tr>${columns.map(column => `<th>${escapeHtml(column)}</th>`).join('')}</tr>`;
  document.querySelector('#source-products-body').innerHTML = rows.map(row => `<tr>${columns.map(column => `<td>${escapeHtml(number(row[column]))}</td>`).join('')}</tr>`).join('');
}
const DESCARTE_COLUMNS = ['Linha (Excel)', 'Motivo', 'Descrição encontrada', 'Fornecedor encontrado'];
function renderDescartes(list) {
  const rows = list || [];
  descartesPanel.hidden = rows.length === 0;
  if (!rows.length) return;
  descartesCount.textContent = `${rows.length} linha(s) não aproveitada(s)`;
  descartesHead.innerHTML = `<tr>${DESCARTE_COLUMNS.map(c => `<th>${escapeHtml(c)}</th>`).join('')}</tr>`;
  descartesBody.innerHTML = rows.map(row => `<tr>${DESCARTE_COLUMNS.map(column => `<td>${escapeHtml(row[column] ?? '-')}</td>`).join('')}</tr>`).join('');
}
function showResult(data) {
  document.querySelector('#results').hidden = false;
  document.querySelector('#result-title').textContent = data.filename || 'Resumo da cotação';
  const downloadLink = document.querySelector('#download-link');
  downloadLink.href = data.download_url;
  downloadLink.hidden = false;
  downloadLink.removeAttribute('disabled');
  downloadLink.removeAttribute('aria-disabled');
  const qualidade = data.analise_fonte?.perfil?.qualidade || {};
  const metrics = [
    ['Total de Itens', data.indicadores['Total de Itens']],
    ['Fornecedores', data.indicadores['Total de Fornecedores']],
    ['Recomendações', data.recomendacoes.length],
    ['Preço elegível', data.indicadores['Itens com Preço Elegível']],
    ['Linhas lidas na aba', qualidade['Linhas físicas analisadas']],
    ['Linhas aproveitadas', qualidade['Linhas válidas']],
    ['Linhas descartadas', qualidade['Linhas descartadas']],
  ];
  document.querySelector('#metrics').innerHTML = metrics.map(([label, value]) => `<div class="metric"><strong>${escapeHtml(number(value))}</strong><span>${escapeHtml(label)}</span></div>`).join('');
  document.querySelector('#notices').innerHTML = (data.avisos || []).map(item => `<div class="notice">${escapeHtml(item)}</div>`).join('');
  renderCharts(data);
  renderSourceAnalysis(data);
  renderDescartes(data.descartes);
  const alerts = data.alertas || [];
  document.querySelector('#alerts-panel').hidden = alerts.length === 0;
  setAlertsOpen(false);
  document.querySelector('#alert-count').textContent = alerts.length ? `${alerts.length} ocorrências` : '';
  alertsList.innerHTML = alerts.map(alert => `<article class="alert-item ${alert.Prioridade === 'MÉDIA' ? 'medium' : ''}"><span class="alert-tag">${escapeHtml(alert.Prioridade)}</span><span class="alert-message">${escapeHtml(alert.Mensagem)}</span></article>`).join('');
  document.querySelector('#recommendation-count').textContent = `${data.recomendacoes.length} itens`;
  renderTable(data.recomendacoes);
  document.querySelector('#insights-list').innerHTML = (data.insights || []).map(item => `<li>${escapeHtml(item)}</li>`).join('');
  const executive = data.analise_executiva || {};
  document.querySelector('#executive-grid').innerHTML = Object.entries(executive).map(([label, value]) => `<div class="executive-item"><strong>${escapeHtml(number(value))}</strong><span>${escapeHtml(label)}</span></div>`).join('');
}
form.addEventListener('submit', async event => {
  event.preventDefault(); errorMessage.hidden = true; resetDiagnostic(); loadingMessage.hidden = false; button.disabled = true; startProgress();
  if (!input.files[0]) { errorMessage.textContent = 'Selecione uma planilha Excel antes de processar.'; errorMessage.hidden = false; loadingMessage.hidden = true; button.disabled = false; clearInterval(progressTimer); return; }
  const data = new FormData(); data.append('file', input.files[0]);
  const sheet = document.querySelector('#sheet-input').value.trim();
  const query = sheet ? `?sheet=${encodeURIComponent(sheet)}` : '';
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15 * 60 * 1000);
  try {
    const response = await fetch(`/api/process${query}`, { method: 'POST', body: data, signal: controller.signal });
    const payload = await response.json();
    if (!response.ok) {
      const detail = payload.detail;
      if (detail && typeof detail === 'object') {
        // Diagnóstico estruturado: mostra o que não foi reconhecido e como corrigir.
        esconderLoading();
        renderDiagnostic(detail);
        throw Object.assign(new Error(detail.mensagem || 'Não foi possível ler a planilha.'), { silencioso: true });
      }
      throw new Error(detail || `Falha no processamento (HTTP ${response.status}).`);
    }
    finishProgress();
    showResult(payload);
  }
  catch (error) {
    if (error.silencioso) {
      // O painel de diagnóstico já explica a falha; não repetir em texto corrido.
      errorMessage.hidden = true;
      return;
    }
    esconderLoading();
    resetProgress();
    const detail = error.name === 'AbortError' ? 'O processamento excedeu o limite de 15 minutos.' : error.message;
    errorMessage.textContent = `Erro no processamento: ${detail}`;
    errorMessage.hidden = false;
  }
  finally { clearTimeout(timeout); setTimeout(() => { loadingMessage.hidden = true; }, 700); button.disabled = false; }
});