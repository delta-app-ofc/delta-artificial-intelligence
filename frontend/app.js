import chat from './tabs/chat.js';
import router from './tabs/router.js';
import consumption from './tabs/consumption.js';
import forecast from './tabs/forecast.js';
import leak from './tabs/leak.js';
import habits from './tabs/habits.js';
import rag from './tabs/rag.js';
import judge from './tabs/judge.js';
import { element, pretty, requestJSON, renderSignals, renderDiagnostics, renderExecutionTerminal, renderMessages } from './shared.js';

const tabs = [chat, router, consumption, forecast, leak, habits, rag, judge];
const icons = ['✦', '⑂', '◷', '↗', '◈', '◎', '▤', '⚖'];
const states = Object.fromEntries(tabs.map(tab => [tab.id, {
  messages: [], draft: '', fields: Object.fromEntries((tab.fields || []).map(field => [field.name, field.defaultValue ?? ''])),
  sessionId: null, busy: false, latest: null, localError: '', chartWarnings: [],
}]));
const byId = id => document.getElementById(id);
let activeId = 'chat';
let config = null;
let configError = '';
let configLoading = false;
const activeTab = () => tabs.find(tab => tab.id === activeId);
const activeState = () => states[activeId];

for (const [index, tab] of tabs.entries()) {
  const button = element('button', 'tab');
  button.id = `tab-${tab.id}`; button.type = 'button'; button.dataset.tab = tab.id;
  button.setAttribute('role', 'tab'); button.setAttribute('aria-controls', 'workspace');
  const icon = element('span', 'tab-icon', icons[index]); icon.setAttribute('aria-hidden', 'true');
  const indicator = element('span', 'tab-indicator'); indicator.setAttribute('aria-hidden', 'true');
  button.append(icon, element('span', '', tab.label), indicator);
  button.addEventListener('click', () => selectTab(tab.id));
  button.addEventListener('keydown', event => {
    let next = index;
    if (event.key === 'ArrowDown' || event.key === 'ArrowRight') next = (index + 1) % tabs.length;
    else if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = tabs.length - 1;
    else return;
    event.preventDefault(); selectTab(tabs[next].id); byId(`tab-${tabs[next].id}`).focus();
  });
  byId('tabs').append(button);
}

function selectTab(id) {
  activeId = id;
  const tab = activeTab(); const state = activeState();
  tabs.forEach(item => {
    const selected = item.id === id; const button = byId(`tab-${item.id}`);
    button.setAttribute('aria-selected', String(selected)); button.tabIndex = selected ? 0 : -1;
  });
  byId('workspace').setAttribute('aria-labelledby', `tab-${id}`);
  byId('page-title').textContent = tab.title;
  byId('page-description').textContent = tab.description;
  byId('workspace-label').textContent = tab.label;
  byId('message-label').textContent = tab.mode === 'judge' ? 'Pergunta original' : 'Sua mensagem';
  byId('message').placeholder = tab.placeholder;
  byId('message').value = state.draft;
  byId('messages').setAttribute('aria-label', `Histórico: ${tab.label}`);
  byId('extra-fields').replaceChildren();
  (tab.fields || []).forEach(field => {
    const wrapper = element('div', 'extra-field');
    const label = element('label', '', field.label); label.htmlFor = `field-${field.name}`;
    const input = element('textarea'); input.id = `field-${field.name}`; input.name = field.name;
    input.required = Boolean(field.required); input.rows = field.type === 'json' ? 5 : 3;
    input.maxLength = 100000; input.value = typeof state.fields[field.name] === 'string' ? state.fields[field.name] : pretty(state.fields[field.name]);
    if (field.placeholder) input.placeholder = field.placeholder;
    input.addEventListener('input', () => { state.fields[field.name] = input.value; input.setCustomValidity(''); });
    wrapper.append(label, input);
    if (field.type === 'json') { const help = element('p', 'field-help', 'JSON válido: um objeto ou uma lista de evidências.'); help.id = `${input.id}-help`; input.setAttribute('aria-describedby', help.id); wrapper.append(help); }
    byId('extra-fields').append(wrapper);
  });
  byId('examples').replaceChildren();
  (tab.examples || []).forEach(example => {
    const button = element('button', 'example', example); button.type = 'button';
    button.addEventListener('click', () => { state.draft = example; byId('message').value = example; byId('message').focus(); });
    byId('examples').append(button);
  });
  byId('tab-notes').replaceChildren(...(tab.notes || []).map(note => element('p', '', note)));
  renderCurrent();
}

function renderPanels() {
  const state = activeState();
  const count = renderSignals(byId('signals'), state, configError);
  state.chartWarnings.forEach(message => byId('signals').append(element('p', 'signal', message)));
  byId('signal-count').textContent = count + state.chartWarnings.length;
  if (configError) {
    const retry = element('button', 'button button-quiet', 'Tentar configuração novamente'); retry.type = 'button';
    retry.disabled = configLoading; retry.addEventListener('click', loadConfig); byId('signals').append(retry);
  }
  renderDiagnostics(byId('diagnostics'), state.latest, state.busy);
  renderExecutionTerminal(byId('execution-terminal'), state.latest, state.busy);
}
function renderCurrent() {
  renderMessages(byId('messages'), activeState().messages, activeTab());
  renderPanels(); renderControls();
}
function renderControls() {
  const tab = activeTab(); const state = activeState();
  byId('send').disabled = state.busy || !config?.enabled;
  byId('send').textContent = state.busy ? 'Executando…' : 'Enviar ↗';
  byId('new-session').disabled = state.busy;
  byId('workspace').setAttribute('aria-busy', String(state.busy));
  byId('session-label').textContent = state.sessionId ? `Sessão ${state.sessionId}` : 'Nova sessão';
  byId('request-status').textContent = state.busy ? 'Aguardando a API. Você pode consultar outras abas.' : configLoading ? 'Carregando configuração…' : !config?.enabled ? 'Console indisponível. Confira os erros e avisos.' : 'Enter para enviar · Shift + Enter para nova linha';
  document.querySelector('.workspace-header .status-dot').classList.toggle('busy', state.busy);
  const agent = config?.agents?.find(item => item.id === tab.id);
  const badge = byId('availability');
  badge.className = 'badge';
  if (configLoading) badge.textContent = 'Carregando configuração';
  else if (!config?.enabled) { badge.textContent = 'Console indisponível'; badge.classList.add('error'); }
  else if (agent?.status === 'pending') { badge.textContent = 'Implementação pendente'; badge.classList.add('pending'); }
  else if (agent?.status === 'error') { badge.textContent = 'Verificar disponibilidade'; badge.classList.add('error'); }
  else if (agent?.status === 'available' || tab.mode === 'chat' || tab.mode === 'router') badge.textContent = 'Pronto para testar';
  else { badge.textContent = 'Disponibilidade não informada'; badge.classList.add('pending'); }
  badge.title = agent?.message || 'A disponibilidade real das integrações é verificada durante a execução.';
}

byId('message').addEventListener('input', () => { activeState().draft = byId('message').value; byId('message').setCustomValidity(''); });
byId('message').addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); byId('request-form').requestSubmit(); }
});
byId('new-session').addEventListener('click', () => {
  const state = activeState();
  if (state.busy) return;
  state.sessionId = null;
  state.messages.push({ role: 'system', text: 'Nova sessão iniciada. As próximas mensagens não usam a sessão anterior; o histórico desta aba continua disponível.' });
  renderCurrent(); byId('message').focus();
});

byId('request-form').addEventListener('submit', async event => {
  event.preventDefault();
  const tab = activeTab(); const state = states[tab.id];
  if (state.busy || !config?.enabled) return;
  const message = state.draft.trim();
  if (!message) { byId('message').setCustomValidity('Escreva uma mensagem para enviar.'); byId('message').reportValidity(); return; }
  const payload = { message, session_id: state.sessionId };
  for (const field of tab.fields || []) {
    const input = byId(`field-${field.name}`); const value = input.value.trim();
    if (field.type === 'json' && value) {
      try {
        const parsed = JSON.parse(value);
        if (parsed === null || typeof parsed !== 'object') throw new Error('object required');
        payload[field.name] = parsed;
      } catch {
        input.setCustomValidity('Informe um JSON válido com um objeto ou uma lista de evidências.'); input.reportValidity(); return;
      }
    } else if (value) payload[field.name] = value;
  }
  state.busy = true; state.localError = ''; state.chartWarnings = []; state.latest = null;
  const context = tab.mode === 'judge' && tab.fields?.length ? { answer: payload.answer, evidence: payload.evidence } : null;
  state.messages.push({ role: 'user', text: message, context });
  state.draft = ''; byId('message').value = ''; renderCurrent();
  const endpoint = tab.mode === 'chat' ? '/playground/chat' : tab.mode === 'router' ? '/playground/router' : `/playground/agents/${encodeURIComponent(tab.id)}`;
  try {
    const result = await requestJSON(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    if (!result || typeof result !== 'object' || typeof result.response !== 'string' || !result.diagnostics) throw new Error('A API retornou um resultado fora do contrato do console.');
    state.latest = result;
    if (typeof result.session_id === 'string') state.sessionId = result.session_id;
    state.messages.push({
      role: 'assistant', text: result.response || 'A API não retornou texto para esta execução.', chart: result.chart_data, result,
      inspect: saved => { state.latest = saved; state.localError = ''; if (activeId === tab.id) renderPanels(); },
      onChartError: warning => { if (!state.chartWarnings.includes(warning)) state.chartWarnings.push(warning); if (activeId === tab.id) renderPanels(); },
    });
  } catch (error) {
    state.localError = error.message || 'Não foi possível concluir a requisição.';
    state.messages.push({ role: 'assistant', text: `Não foi possível concluir esta execução. ${state.localError}` });
    // A mensagem permanece recuperável para uma nova tentativa sem perder o histórico.
    if (!state.draft) state.draft = message;
  } finally {
    state.busy = false;
    // A resposta pertence à aba capturada no envio, mesmo que a pessoa mude de aba.
    if (activeId === tab.id) { byId('message').value = state.draft; renderCurrent(); }
  }
});

async function loadConfig() {
  if (configLoading) return;
  configLoading = true; renderPanels(); renderControls();
  try {
    const value = await requestJSON('/playground/config');
    if (value.user_id !== 12345679 || value.test_label !== 'teste_agentes_25_10' || !Array.isArray(value.agents)) throw new Error('A configuração retornada não corresponde ao usuário e ao teste fixos deste console.');
    config = value; configError = value.enabled ? '' : 'O servidor desativou o console de testes.';
  } catch (error) { config = null; configError = error.message; }
  finally { configLoading = false; renderPanels(); renderControls(); }
}
const media = window.matchMedia('(max-width: 950px)');
const updateOrientation = () => byId('tabs').setAttribute('aria-orientation', media.matches ? 'horizontal' : 'vertical');
media.addEventListener('change', updateOrientation); updateOrientation();
selectTab('chat');
loadConfig();
