export default {
  id: 'monitor',
  label: 'Monitor',
  title: 'Monitor · observabilidade',
  description: 'Custo, latência, erros, resolução e ROI das últimas requisições do chat completo.',
  mode: 'monitor',
  notes: [],

  // Todo texto entra no DOM como texto; os números vêm do resumo agregado da API.
  async render(target, { element, requestJSON }) {
    target.replaceChildren(element('p', 'neutral-message', 'Carregando métricas…'));
    let data;
    try { data = await requestJSON('/playground/observability'); }
    catch (error) { target.replaceChildren(element('p', 'signal error', error.message)); return; }

    const money = value => (value === null || value === undefined ? 'n/d' : `US$ ${Number(value).toFixed(4)}`);
    const card = (label, value, hint = '') => {
      const node = element('div', 'panel');
      node.style.padding = '12px';
      node.append(element('small', '', label), element('strong', '', value));
      if (hint) node.append(element('small', '', hint));
      node.querySelectorAll('small, strong').forEach(item => { item.style.display = 'block'; });
      return node;
    };
    const lat = data.latency_total_ms;
    const cards = element('div', '');
    cards.style.cssText = 'display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin-bottom:14px';
    cards.append(
      card('Requisições', data.requests),
      card('Tempo total p95', `${lat.p95} ms`, `média ${lat.avg} ms · p50 ${lat.p50} ms`),
      card('Índice de erros', `${(data.error_rate * 100).toFixed(2)}%`, data.slo.ok ? 'SLO atendido' : 'SLO violado'),
      card('Taxa de resolução', `${(data.resolution_rate * 100).toFixed(1)}%`, `${data.resolutions} resoluções`),
      card('Custo por resolução', money(data.cost_per_resolution_usd)),
      card('ROI', data.roi === null ? 'n/d' : data.roi.toFixed(2), 'retorno sobre o custo de IA'),
      card('Custo total', money(data.cost_usd), `${data.tokens.input} tokens de entrada · ${data.tokens.output} de saída`),
    );

    const actions = element('div', '');
    const refresh = element('button', 'button button-quiet', 'Atualizar'); refresh.type = 'button';
    refresh.addEventListener('click', () => this.render(target, { element, requestJSON }));
    const pdf = element('a', 'button', 'Exportar PDF ⤓');
    pdf.href = '/playground/observability/report.pdf'; pdf.setAttribute('download', 'delta-observabilidade.pdf');
    actions.style.cssText = 'display:flex;gap:8px;margin-bottom:12px';
    actions.append(refresh, pdf);

    const charts = element('div', '');
    charts.style.cssText = 'display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px';
    const chartIds = ['mon-latency', 'mon-nodes', 'mon-cost'];
    chartIds.forEach(id => { const box = element('div', 'panel'); box.id = id; box.style.minHeight = '280px'; charts.append(box); });

    const projection = element('table', 'projection');
    projection.style.cssText = 'width:100%;margin-top:14px;border-collapse:collapse';
    const head = element('tr');
    ['Cenário', 'Usuários/sem.', 'Perguntas/sem.', 'Custo/sem. (US$)', 'Custo/mês (US$)', 'Custo/resolução', 'ROI']
      .forEach(label => head.append(element('th', '', label)));
    projection.append(head);
    data.projection.forEach(row => {
      const tr = element('tr');
      [row.scenario, row.users_per_week, row.requests_per_week, row.cost_week_usd, row.cost_month_usd,
        row.cost_per_resolution_usd ?? 'n/d', row.roi ?? 'n/d'].forEach(value => tr.append(element('td', '', value)));
      projection.append(tr);
    });
    const note = element('p', 'neutral-message',
      `Premissas: ${data.assumptions.questions_per_user_per_week} perguntas/usuário/semana, atendimento a US$ ${data.assumptions.support_cost_per_resolution_usd}. `
      + `Preço assumido: ${data.assumed_price_models.join(', ') || 'nenhum'}. Dados de teste não representam uso real.`);

    target.replaceChildren(actions, cards, charts, element('h3', '', 'Projeção: 100 e 1000 usuários por semana'), projection, note);

    if (!window.Plotly) return;
    const layout = title => ({ title: { text: title, font: { size: 13 } }, margin: { t: 36, l: 44, r: 12, b: 36 }, height: 280 });
    const series = data.series;
    Plotly.newPlot('mon-latency', [{ x: series.map(item => item.at), y: series.map(item => item.total_ms), type: 'scatter', mode: 'lines+markers' }],
      layout('Tempo total por requisição (ms)'), { displayModeBar: false, responsive: true });
    const nodes = Object.entries(data.latency_by_node_ms);
    Plotly.newPlot('mon-nodes', [{ x: nodes.map(([name]) => name), y: nodes.map(([, value]) => value.p95), type: 'bar', name: 'p95' },
      { x: nodes.map(([name]) => name), y: nodes.map(([, value]) => value.avg), type: 'bar', name: 'média' }],
      layout('Latência por etapa (ms)'), { displayModeBar: false, responsive: true });
    const costs = Object.entries(data.cost_by_component_usd);
    Plotly.newPlot('mon-cost', [{ labels: costs.map(([name]) => name), values: costs.map(([, value]) => value), type: 'pie' }],
      layout('Custo por componente'), { displayModeBar: false, responsive: true });
  },
};
