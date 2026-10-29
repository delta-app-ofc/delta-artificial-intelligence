// A saída do terminal é texto: mensagens e JSON nunca são interpretados como HTML.
function node(tag, className, text = '') {
  const item = document.createElement(tag);
  item.className = className;
  item.textContent = text;
  return item;
}

function inline(value) {
  return value === undefined || value === null ? '—' : String(value).replace(/[\r\n\t]+/g, ' ');
}

function json(value) {
  return JSON.stringify(value, null, 2);
}

function tone(status) {
  if (['error', 'unavailable'].includes(status)) return 'error';
  if (['partial', 'rejected', 'reject', 'correct'].includes(status)) return 'warning';
  return 'info';
}

function outputBlocks(result, view) {
  const diagnostics = result.diagnostics || {};
  if (view === 'events') {
    const blocks = (diagnostics.events || []).map((event, index) => ({
      title: `EVENTO #${String(index + 1).padStart(3, '0')} · ${inline(event.event)}`,
      tone: event.event === 'llm.fallback' ? 'warning' : tone(event.status),
      text: [
        `${inline(event.timestamp)} [${inline(event.status).toUpperCase()}]`,
        `${inline(event.component)} → ${inline(event.operation)}`,
        ...(typeof event.duration_ms === 'number' ? [`duração: ${event.duration_ms} ms`] : []),
        ...(event.metadata && Object.keys(event.metadata).length ? [json(event.metadata)] : []),
      ].join('\n'),
    }));
    if (diagnostics.dropped_event_count) blocks.unshift({ title: 'AVISO', tone: 'warning',
      text: `${diagnostics.dropped_event_count} eventos anteriores excederam o limite do diagnóstico.` });
    return blocks.length ? blocks : [{ title: 'EVENTOS', text: 'Nenhum evento registrado.', tone: 'info' }];
  }

  const blocks = (result.agent_results || []).map((agent, index) => ({
    title: `AGENTE #${index + 1} · ${inline(agent.agent || agent.agent_id || agent.id)}`,
    tone: tone(agent.status),
    text: `status: ${inline(agent.status)}\n\nMENSAGEM DO AGENTE:\n${agent.answer ?? agent.response ?? '(sem mensagem)'}\n\nJSON DO AGENTE:\n${json(agent)}`,
  }));
  (result.judge_results || []).forEach((judge, index) => blocks.push({
    title: `JEV · AVALIAÇÃO #${index + 1}`,
    tone: tone(judge.status === 'unavailable' ? judge.status : judge.decision),
    text: `JSON DA AVALIAÇÃO DO JEV:\n${json(judge)}`,
  }));
  blocks.push({ title: 'RESPOSTA FINAL', tone: tone(result.status),
    text: result.response || '(a execução não produziu uma resposta final)' });
  return blocks;
}

function blockText(block) {
  return `========== INÍCIO · ${block.title} ==========\n\n${block.text}\n\n---------- FIM · ${block.title} ----------`;
}

export function executionLogText(result, view = 'responses') {
  return `REQUEST_ID: ${inline(result.diagnostics?.request_id)}\n\n${outputBlocks(result, view).map(blockText).join('\n\n')}`;
}

export function createExecutionTerminal(result, { view = 'responses', expanded = false } = {}) {
  const terminal = node('div', 'event-terminal');
  const toolbar = node('div', 'event-terminal-toolbar');
  const views = node('div', 'event-terminal-actions');
  views.setAttribute('role', 'group');
  views.setAttribute('aria-label', 'Conteúdo do terminal');
  const buttons = [];
  const output = node('div', 'event-terminal-output');
  output.tabIndex = 0;
  output.setAttribute('role', 'region');
  output.setAttribute('aria-label', 'Terminal da execução; use as setas para rolar');

  function render() {
    output.replaceChildren(node('p', 'event-terminal-request', `request_id: ${inline(result.diagnostics?.request_id)}`));
    outputBlocks(result, view).forEach(block => output.append(node('pre', `event-terminal-entry ${block.tone}`, blockText(block))));
    output.scrollTop = 0;
    buttons.forEach(([button, mode]) => button.setAttribute('aria-pressed', String(mode === view)));
  }

  [['Respostas e Jev', 'responses'], ['Eventos', 'events']].forEach(([label, mode]) => {
    const button = node('button', 'button button-quiet', label);
    button.type = 'button';
    button.addEventListener('click', () => { view = mode; render(); });
    buttons.push([button, mode]);
    views.append(button);
  });
  const actions = node('div', 'event-terminal-actions');
  const copy = node('button', 'button button-quiet', 'Copiar');
  copy.type = 'button';
  copy.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(executionLogText(result, view));
      copy.textContent = 'Copiado';
    } catch {
      copy.textContent = 'Selecione o texto para copiar';
    }
  });
  actions.append(copy);
  if (!expanded) {
    const expand = node('button', 'button button-quiet', 'Ampliar');
    expand.type = 'button';
    expand.addEventListener('click', () => {
      const dialog = node('dialog', 'event-terminal-dialog');
      dialog.setAttribute('aria-label', 'Terminal da execução ampliado');
      const header = node('header', 'event-terminal-toolbar');
      header.append(node('strong', '', 'Terminal da execução'));
      const close = node('button', 'button button-quiet', 'Fechar');
      close.type = 'button';
      close.addEventListener('click', () => dialog.close());
      header.append(close);
      dialog.append(header, createExecutionTerminal(result, { view, expanded: true }));
      dialog.addEventListener('close', () => { dialog.remove(); if (expand.isConnected) expand.focus(); }, { once: true });
      document.body.append(dialog);
      dialog.showModal();
    });
    actions.append(expand);
  }
  toolbar.append(views, actions);
  terminal.append(toolbar, output);
  render();
  return terminal;
}
