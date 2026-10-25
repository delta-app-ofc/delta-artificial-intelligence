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
  const raw = await response.text();
  let body;
  try { body = JSON.parse(raw); }
  catch { throw new Error(`A API retornou uma resposta inválida (HTTP ${response.status}).`); }
  if (!response.ok) {
    const error = new Error(errorMessage(body.detail ?? body));
    error.status = response.status;
    error.body = body;
    throw error;
  }
  return body;
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
  const models = section('Modelos');
  if (!diagnostics.models?.length) models.append(element('p', 'neutral-message', 'Nenhum modelo registrado.'));
  else diagnostics.models.forEach(model => {
    const card = element('div', 'model-card');
    card.append(element('strong', '', model.component || 'Modelo'), element('p', '', `${model.provider || 'Provedor não informado'} · ${model.model || 'Modelo não informado'}`), element('p', '', `Status: ${model.status || 'não informado'} · ${duration(model.duration_ms)}`), element('p', '', `Fallback: ${model.fallback === true ? 'sim' : model.fallback === false ? 'não' : pretty(model.fallback)}`));
    models.append(card);
  });
  target.append(models);
  const tools = section('Ferramentas');
  if (!diagnostics.tools?.length) tools.append(element('p', 'neutral-message', 'Nenhuma ferramenta registrada.'));
  else diagnostics.tools.forEach(tool => tools.append(details(`${tool.name || 'Ferramenta'} · ${tool.status || 'não informado'}`, [['Agente', tool.agent], ['Entrada', tool.input], ['Saída', tool.output]])));
  target.append(tools);
  const stages = section('Etapas');
  if (!diagnostics.stages?.length) stages.append(element('p', 'neutral-message', 'Nenhuma etapa registrada.'));
  else diagnostics.stages.forEach(stage => stages.append(row(`${stage.stage} · ${stage.status}`, duration(stage.duration_ms))));
  target.append(stages);
  if (result.agent_results?.length) {
    const results = section('Resultados dos agentes');
    result.agent_results.forEach(agent => results.append(details(`${agent.agent || agent.agent_id || agent.id || 'Agente'} · ${agent.status || 'resultado'}`, [['Resultado retornado', agent]])));
    target.append(results);
  }
  if (result.judge_results?.length) {
    const judgments = section('Decisões do Juiz Jev');
    result.judge_results.forEach((judge, index) => judgments.append(details(
      `Avaliação ${index + 1} · ${judge.decision || judge.status || 'resultado'}`,
      [['Status', judge.status], ['Gravidade', judge.severity],
        ['Confiança', judge.confidence], ['Códigos Python', judge.reason_codes],
        ['Justificativa Python', judge.justification], ['Sinais adicionais', judge.assessment]],
    )));
    target.append(judgments);
  }
  const metadata = section('Requisição');
  metadata.append(row('ID', diagnostics.request_id), row('Modo', diagnostics.mode), row('Usuário', diagnostics.user_id), row('Teste', diagnostics.test_label));
  target.append(metadata);
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
    const node = element('article', `message ${message.role}`);
    const meta = element('div', 'message-meta');
    meta.append(element('span', 'message-role', message.role === 'user' ? '↗' : 'δ'), element('span', '', message.role === 'user' ? 'Você' : 'Delta'));
    node.append(meta, element('div', 'message-body', message.text));
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
