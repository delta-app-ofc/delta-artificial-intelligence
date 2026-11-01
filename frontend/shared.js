import { createExecutionTerminal } from "./event-terminal.js";
import { renderMarkdown } from "./markdown.js";

// Todo conteúdo retornado pela API entra no DOM como texto, sem HTML do modelo.
export function element(tag, className = '', text = '') {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== '') node.textContent = String(text);
  return node;
}
export function pretty(value) {
  if (value === undefined || value === null) return 'Não informado';
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2);
}
export function duration(value) {
  return typeof value === 'number' && Number.isFinite(value)
    ? (value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${Math.round(value)} ms`)
    : 'Não informado';
}
export function errorMessage(value) {
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.map(errorMessage).join('\n');
  if (value && typeof value === 'object') {
    const message = value.message || value.msg || value.detail;
    const location = Array.isArray(value.loc) ? `${value.loc.join('.')} — ` : '';
    return location + (message ? errorMessage(message) : pretty(value));
  }
  return 'Falha sem mensagem retornada pela API.';
}
export async function requestJSON(url, options = {}) {
  let response;
  try { response = await fetch(url, { credentials: 'same-origin', ...options }); }
  catch { throw new Error('Não foi possível alcançar a API. Verifique o servidor e a conexão e tente novamente.'); }
  const requestId = response.headers.get('X-Request-ID');
  const reference = requestId ? ` Requisição: ${requestId}.` : '';
  const raw = await response.text();
  let body;
  try { body = JSON.parse(raw); }
  catch { throw new Error(`A API retornou uma resposta inválida (HTTP ${response.status}).${reference}`); }
  if (!response.ok) {
    const error = new Error(errorMessage(body?.detail ?? body) + reference);
    error.requestId = requestId;
    error.status = response.status;
    error.body = body;
    throw error;
  }
  return body;
}
// Lê um fluxo SSE (text/event-stream) do console: cada `stage` chama onStage e o `result` é devolvido.
export async function streamChat(url, options, onStage) {
  let response;
  try { response = await fetch(url, { credentials: 'same-origin', ...options }); }
  catch { throw new Error('Não foi possível alcançar a API. Verifique o servidor e a conexão e tente novamente.'); }
  const requestId = response.headers.get('X-Request-ID');
  const reference = requestId ? ` Requisição: ${requestId}.` : '';
  if (!response.ok || !response.body) {
    const raw = await response.text();
    let body;
    try { body = JSON.parse(raw); }
    catch { throw new Error(`A API retornou uma resposta inválida (HTTP ${response.status}).${reference}`); }
    const error = new Error(errorMessage(body?.detail ?? body) + reference);
    error.requestId = requestId; error.status = response.status; error.body = body;
    throw error;
  }
  let result = null;
  const handle = block => {
    if (!block.trim() || block.startsWith(':')) return;
    let name = 'message'; let data = '';
    for (const line of block.split('\n')) {
      if (line.startsWith('event: ')) name = line.slice(7);
      else if (line.startsWith('data: ')) data += line.slice(6);
    }
    let parsed;
    try { parsed = JSON.parse(data); } catch { return; }
    if (name === 'stage') onStage(parsed);
    else if (name === 'result') result = parsed;
    else if (name === 'error') {
      const error = new Error(errorMessage(parsed.detail) + reference);
      error.requestId = requestId;
      throw error;
    }
  };
  const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    buffer = (buffer + decoder.decode(value || new Uint8Array(), { stream: !done })).replace(/\r\n/g, '\n');
    let index;
    while ((index = buffer.indexOf('\n\n')) >= 0) { handle(buffer.slice(0, index)); buffer = buffer.slice(index + 2); }
    if (done) break;
  }
  handle(buffer);
  if (!result) throw new Error('A execução terminou sem resultado.' + reference);
  return result;
}
export function formatSeconds(ms) { return `${(Math.max(0, ms) / 1000).toFixed(1)} s`; }
// Cartão de "em andamento": bolinhas que crescem e sobem, o rótulo da etapa atual, o tempo e as etapas já feitas.
export function renderProgress(progress) {
  const node = element('article', 'message progress');
  node.setAttribute('aria-label', 'Execução em andamento');
  const meta = element('div', 'message-meta');
  meta.append(element('span', 'message-role', 'δ'), element('span', '', 'Delta'));
  const card = element('div', 'progress-card');
  const bubbles = element('span', 'progress-bubbles'); bubbles.setAttribute('aria-hidden', 'true');
  bubbles.append(element('i', 'bubble b1'), element('i', 'bubble b2'), element('i', 'bubble b3'));
  const info = element('div', 'progress-info');
  const timer = element('span', 'progress-timer', formatSeconds(performance.now() - progress.startedAt));
  timer.dataset.startedAt = String(progress.startedAt);
  info.append(element('strong', 'progress-current', progress.steps.at(-1)?.label || progress.idle || 'Executando…'), timer);
  card.append(bubbles, info);
  node.append(meta, card);
  if (progress.steps.length > 1) node.append(stepList(progress.steps.slice(0, -1), progress.steps.at(-1).at));
  return node;
}
// Lista de etapas com a duração de cada uma (até o início da seguinte ou do fim informado).
function stepList(steps, endMs) {
  const list = element('ol', 'progress-steps');
  steps.forEach((step, index) => {
    const next = steps[index + 1]?.at ?? endMs;
    const item = element('li');
    item.append(element('span', 'step-label', step.label), element('span', 'step-time', typeof next === 'number' ? formatSeconds(next - step.at) : ''));
    list.append(item);
  });
  return list;
}
function stepsDetails(steps, totalMs) {
  const node = element('details', 'tool-detail steps-detail');
  node.append(element('summary', '', `Etapas desta resposta · ${steps.length}${typeof totalMs === 'number' ? ` · ${formatSeconds(totalMs)}` : ''}`));
  node.append(stepList(steps, totalMs));
  return node;
}
function section(title) {
  const node = element('section', 'diag-section');
  node.append(element('h3', '', title));
  return node;
}
function row(label, value) {
  const node = element('div', 'diag-row');
  node.append(element('span', '', label), element('span', '', value ?? 'Não informado'));
  return node;
}
function listChips(values, skipped = false) {
  const node = element('div', 'chips');
  if (!Array.isArray(values) || !values.length) node.append(element('span', 'neutral-message', 'Nenhum'));
  else values.forEach(value => node.append(element('span', `chip${skipped ? ' skipped' : ''}`, typeof value === 'string' ? value : pretty(value))));
  return node;
}
function details(title, pairs) {
  const node = element('details', 'tool-detail');
  node.append(element('summary', '', title));
  pairs.forEach(([label, value]) => node.append(element('h4', '', label), element('pre', '', pretty(value))));
  return node;
}
export function renderSignals(target, state, configError = '') {
  target.replaceChildren();
  const signals = [];
  if (configError) signals.push({ severity: 'error', title: 'Configuração', message: configError });
  if (state.localError) signals.push({ severity: 'error', title: 'Requisição', message: state.localError });
  const diagnostics = state.latest?.diagnostics || {};
  (diagnostics.errors || []).forEach(error => signals.push({ severity: 'error', title: [error.stage, error.code].filter(Boolean).join(' · ') || 'Erro', message: errorMessage(error) }));
  (diagnostics.events || []).filter(event => event.event === 'guardrail.rejected').forEach(event => {
    if ((diagnostics.errors || []).some(error => error.code === event.metadata?.outcome)) return;
    signals.push({ severity: 'warning', title: 'Mensagem bloqueada',
      message: `A etapa ${event.component || 'de validação'} bloqueou esta execução.` });
  });
  (diagnostics.warnings || []).forEach(warning => signals.push({ severity: 'warning', title: 'Aviso', message: errorMessage(warning) }));
  if (!signals.length) target.append(element('p', 'neutral-message', state.latest ? 'Nenhum erro ou aviso nesta execução.' : 'Erros e avisos da execução aparecerão aqui.'));
  signals.forEach(signal => {
    const node = element('div', `signal ${signal.severity}`);
    node.append(element('strong', '', signal.title), element('span', '', signal.message));
    target.append(node);
  });
  return signals.length;
}
const statusLabels = { success: 'Concluído', partial: 'Parcial', error: 'Falha', skipped: 'Não executado', pending: 'Pendente' };
export function renderDiagnostics(target, result, busy = false) {
  target.replaceChildren();
  if (!result) {
    const empty = element('div', 'diagnostic-empty');
    empty.append(element('div', 'mini-symbol', '⌁'), element('strong', '', busy ? 'Execução em andamento' : 'Cada resposta tem um caminho.'), element('p', '', busy ? 'Aguardando os diagnósticos retornados pelo servidor.' : 'Envie uma mensagem para inspecionar agentes, modelos e ferramentas utilizados de verdade.'));
    target.append(empty);
    return;
  }
  const diagnostics = result.diagnostics || {};
  const headline = element('div', 'diag-status');
  headline.append(element('strong', '', statusLabels[result.status] || result.status || 'Resposta recebida'), element('span', '', duration(diagnostics.duration_ms)));
  target.append(headline);
  const routing = section('Roteamento');
  routing.append(row('Intenção', diagnostics.routing?.intent), row('Complexidade', diagnostics.routing?.complexity));
  target.append(routing);
  [['Selecionados', diagnostics.selected_agents], ['Executados', diagnostics.executed_agents], ['Não executados', diagnostics.skipped_agents]].forEach(([label, values]) => {
    const group = section(label); group.append(listChips(values, label === 'Não executados')); target.append(group);
  });
  if (diagnostics.errors?.length) {
    const failures = section('Origem das falhas');
    diagnostics.errors.forEach(error => failures.append(details(
      `${error.stage || 'Execução'} · ${error.code || 'Erro'}`,
      [['Mensagem', error.message], ['ID do erro', error.error_id],
        ['Operação', error.operation], ['Causa original', error.cause_type],
        ['Localização', error.location], ['Cadeia de causas', error.cause_chain]],
    )));
    target.append(failures);
  }
  const technical = element('details', 'tool-detail');
  technical.append(element('summary', '', 'Modelos, ferramentas e etapas'));
  const models = section('Modelos');
  if (!diagnostics.models?.length) models.append(element('p', 'neutral-message', 'Nenhum modelo registrado.'));
  else diagnostics.models.forEach(model => {
    const card = element('div', 'model-card');
    card.append(element('strong', '', model.component || 'Modelo'), element('p', '', `${model.provider || 'Provedor não informado'} · ${model.model || 'Modelo não informado'}${model.reasoning_effort ? ` · esforço: ${model.reasoning_effort}` : ''}`), element('p', '', `Status: ${model.status || 'não informado'} · ${duration(model.duration_ms)}`), element('p', '', `Fallback: ${model.fallback === true ? 'sim' : model.fallback === false ? 'não' : pretty(model.fallback)}`));
    models.append(card);
  });
  technical.append(models);
  const tools = section('Ferramentas');
  if (!diagnostics.tools?.length) tools.append(element('p', 'neutral-message', 'Nenhuma ferramenta registrada.'));
  else diagnostics.tools.forEach(tool => tools.append(details(`${tool.name || 'Ferramenta'} · ${tool.status || 'não informado'}`, [['Agente', tool.agent], ['Entrada', tool.input], ['Saída', tool.output]])));
  technical.append(tools);
  const stages = section('Etapas');
  if (!diagnostics.stages?.length) stages.append(element('p', 'neutral-message', 'Nenhuma etapa registrada.'));
  else diagnostics.stages.forEach(stage => stages.append(row(`${stage.stage} · ${stage.status}`, duration(stage.duration_ms))));
  technical.append(stages);
  target.append(technical);
  const metadata = section('Requisição');
  metadata.append(row('ID', diagnostics.request_id), row('Modo', diagnostics.mode), row('Usuário', diagnostics.user_id), row('Teste', diagnostics.test_label));
  target.append(metadata);
}
export function renderExecutionTerminal(target, result, busy = false) {
  target.replaceChildren();
  if (!result) {
    target.append(element('p', 'event-terminal-notice', busy
      ? 'Aguardando as mensagens dos agentes e as avaliações do Jev…'
      : 'Envie uma mensagem para inspecionar as respostas dos agentes, o JSON do Jev e os eventos.'));
    return;
  }
  target.append(createExecutionTerminal(result));
}
export function renderMessages(target, messages, tab) {
  if (window.Plotly) target.querySelectorAll('.chart').forEach(chart => window.Plotly.purge(chart));
  target.replaceChildren();
  if (!messages.length) {
    const empty = element('div', 'empty-state');
    empty.append(element('div', 'empty-symbol', '✦'), element('h2', '', tab.mode === 'chat' ? 'Vamos entender sua água?' : `Experimente ${tab.label}`), element('p', '', 'Faça uma pergunta ou escolha uma sugestão abaixo. A resposta e os detalhes da execução ficam juntos, nesta aba.'));
    target.append(empty);
    return;
  }
  messages.forEach(message => {
    if (message.role === 'progress') { message.node = renderProgress(message); target.append(message.node); return; }
    const node = element('article', `message ${message.role}`);
    const meta = element('div', 'message-meta');
    meta.append(element('span', 'message-role', message.role === 'user' ? '↗' : 'δ'), element('span', '', message.role === 'user' ? 'Você' : 'Delta'));
    const body = element('div', 'message-body');
    if (message.role === 'user' || message.role === 'system') body.textContent = String(message.text ?? '');
    else renderMarkdown(body, message.text);
    node.append(meta, body);
    if (message.context) node.append(details('Ver entrada da avaliação', [['Resposta e evidências enviadas', message.context]]));
    if (message.result) {
      const tools = message.result.diagnostics?.tools || [];
      const usedTools = element('section', 'message-tools');
      usedTools.append(element('strong', '', 'Ferramentas usadas · ' + tools.length));
      if (!tools.length) usedTools.append(element('p', 'neutral-message', 'Nenhuma ferramenta registrada nesta resposta.'));
      else tools.forEach(tool => usedTools.append(details(
        `${tool.name || 'Ferramenta'} · ${tool.status || 'não informado'}`,
        [['Agente', tool.agent], ['Entrada', tool.input], ['Saída', tool.output]],
      )));
      node.append(usedTools);
      if (message.steps?.length) node.append(stepsDetails(message.steps, message.totalMs));
      const inspect = element('button', 'button button-quiet', 'Inspecionar esta execução');
      inspect.type = 'button'; inspect.addEventListener('click', () => message.inspect(message.result));
      node.append(inspect);
    }
    target.append(node);
    if (message.chart) renderChart(node, message.chart, message.onChartError);
  });
  target.scrollTop = target.scrollHeight;
}
function renderChart(parent, figure, onError) {
  const chart = element('div', 'chart'); chart.setAttribute('aria-label', 'Gráfico retornado pelo agente'); parent.append(chart);
  const fail = message => {
    if (!chart.isConnected) return;
    chart.replaceWith(element('p', 'chart-error', message));
    onError?.(message);
  };
  if (!window.Plotly) { fail('O gráfico não pôde ser exibido: a biblioteca Plotly local não está disponível.'); return; }
  if (!figure || !Array.isArray(figure.data)) { fail('O gráfico retornado não contém uma figura Plotly válida.'); return; }
  const layout = { ...figure.layout, autosize: true, paper_bgcolor: '#202325', plot_bgcolor: '#202325', font: { ...figure.layout?.font, color: '#d6e3ee', family: 'Google Sans Flex, sans-serif' }, margin: { l: 50, r: 20, t: 50, b: 50, ...figure.layout?.margin } };
  delete layout.width;
  try {
    Promise.resolve(window.Plotly.react(chart, figure.data, layout, { responsive: true, displaylogo: false, displayModeBar: false })).catch(() => fail('Não foi possível renderizar o gráfico retornado pelo agente.'));
  } catch { fail('Não foi possível renderizar o gráfico retornado pelo agente.'); }
}
