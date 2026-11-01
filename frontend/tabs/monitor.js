export default {
  id: 'monitor',
  label: 'Monitor',
  title: 'Monitor · observabilidade',
  description: 'Confiabilidade, latência, custo e retorno das últimas requisições do chat completo.',
  mode: 'monitor',
  notes: [],

  // Todo texto entra no DOM como texto; os números vêm do resumo agregado da API.
  async render(target, { element, requestJSON }) {
    target.replaceChildren(element('p', 'neutral-message', 'Carregando métricas…'));
    let data;
    try { data = await requestJSON('/playground/observability'); }
    catch (error) { target.replaceChildren(element('p', 'signal error', error.message)); return; }

    const usd = value => (value === null || value === undefined ? 'n/d' : `US$ ${Number(value).toFixed(4)}`);
    const pct = value => `${(value * 100).toFixed(1)}%`;
    const secs = value => (value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${Math.round(value)} ms`);
    const num = value => Number(value).toLocaleString('pt-BR');

    const kpi = (label, value, hint = '', tone = '') => {
      const node = element('div', `mon-kpi${tone ? ` ${tone}` : ''}`);
      node.append(element('span', 'mon-kpi-label', label), element('strong', '', value));
      if (hint) node.append(element('span', 'mon-kpi-hint', hint));
      return node;
    };
    const group = (title, ...cards) => {
      const section = element('section', 'mon-group');
      const grid = element('div', 'mon-kpis');
      grid.append(...cards);
      section.append(element('h3', 'mon-group-title', title), grid);
      return section;
    };

    const lat = data.latency_total_ms;
    const slo = data.slo;
    const sloTone = slo.ok === null ? '' : slo.ok ? 'ok' : 'bad';
    const sloText = slo.ok === null ? 'SLO sem dados' : slo.ok ? 'SLO atendido' : 'SLO violado';
    const out = data.outcomes;

    const toolbar = element('div', 'mon-toolbar');
    const refresh = element('button', 'button button-quiet', 'Atualizar'); refresh.type = 'button';
    refresh.addEventListener('click', () => this.render(target, { element, requestJSON }));
    const pdf = element('a', 'button button-primary', 'Exportar PDF');
    pdf.href = '/playground/observability/report.pdf'; pdf.setAttribute('download', 'delta-observabilidade.pdf');
    toolbar.append(element('span', 'mon-sample', `${num(data.requests)} requisições analisadas`), refresh, pdf);

    const groups = element('div', 'mon-groups');
    groups.append(
      group('Confiabilidade',
        kpi('Índice de erros', pct(data.error_rate), `limite ${pct(slo.error_rate_limit)}`, !data.requests ? '' : data.error_rate <= slo.error_rate_limit ? 'ok' : 'bad'),
        kpi('Sucesso', num(out.success), `${num(out.partial)} parciais`),
        kpi('Falhas', num(out.error), 'requisições com erro', out.error ? 'bad' : ''),
        kpi('Bloqueios', num(out.rejected), 'guardrail ou Juiz'),
        kpi('Fallbacks', num(data.fallback_calls), 'chamadas ao modelo reserva')),
      group('Latência',
        kpi('Tempo total p95', secs(lat.p95), `limite ${secs(slo.latency_p95_limit_ms)} · ${sloText}`, sloTone),
        kpi('Mediana (p50)', secs(lat.p50), `média ${secs(lat.avg)}`),
        kpi('Pior caso (p99)', secs(lat.p99)),
        kpi('Orquestração', secs(data.overhead_ms.p50), 'tempo entre etapas (p50)')),
      group('Custo',
        kpi('Custo total', usd(data.cost_usd), `${num(data.usage.input_tokens)} tokens de entrada · ${num(data.usage.output_tokens)} de saída`),
        kpi('Custo por requisição', usd(data.cost_per_request_usd), `${num(data.volume_per_request)} tokens em média`),
        kpi('Chamadas ao modelo', String(data.model_calls_per_request), 'por requisição'),
        kpi('Revisões do Juiz', pct(data.revision_rate), 'requisições com correção'),
        kpi('Embeddings', usd(data.embedding_cost_usd), data.embedding_uncounted ? `${num(data.embedding_uncounted)} chamadas sem contagem` : `${num(data.usage.embedding_tokens)} tokens contados`),
        kpi('Jev', usd(data.jev_cost_usd), `${num(data.usage.jev_tokens)} tokens de entrada`)),
      group('Uso',
        kpi('Usuários distintos', data.distinct_users ? num(data.distinct_users) : 'n/d', data.distinct_users ? 'no período analisado' : 'defina OBS_HASH_SECRET'),
        kpi('Perguntas por usuário', data.questions_per_user === null ? 'n/d' : String(data.questions_per_user), 'medido, não cenário'),
        kpi('Cliente que mais gasta', Object.keys(data.cost_by_client)[0] || 'n/d', Object.keys(data.cost_by_client).length ? usd(Object.values(data.cost_by_client)[0].cost_usd) : '')),
      group('Retorno',
        kpi('Taxa de resolução', pct(data.resolution_rate), `${num(data.resolutions)} resoluções`),
        kpi('Custo por resolução', usd(data.cost_per_resolution_usd)),
        kpi('ROI', data.roi === null ? 'n/d' : data.roi.toFixed(2), 'retorno sobre o custo de IA'),
        kpi('Economia estimada', usd(data.savings_usd), 'atendimentos evitados − custo')),
    );

    const panel = (title, id, tag) => {
      const box = element('section', 'panel mon-chart-panel');
      const head = element('header', 'panel-heading');
      head.append(element('h2', '', title), element('span', 'live-indicator', tag));
      const plot = element('div', 'mon-plot'); plot.id = id;
      box.append(head, plot);
      return box;
    };
    const charts = element('div', 'mon-charts');
    charts.append(
      panel('Tempo total por requisição', 'mon-series', 'LATÊNCIA'),
      panel('Latência por etapa', 'mon-nodes', 'P50 · P95'),
      panel('Custo por componente', 'mon-cost', 'USD'),
      panel('Resultado das requisições', 'mon-outcomes', 'ERROS'),
      panel('Custo por cliente', 'mon-clients', 'APP · WEB'),
    );

    const projection = element('section', 'panel mon-table-panel');
    const projectionHead = element('header', 'panel-heading');
    projectionHead.append(element('h2', '', 'Projeção: 100 e 1000 usuários por semana'), element('span', 'live-indicator', 'ESTIMATIVA'));
    const table = element('table', 'mon-table');
    const thead = element('thead');
    const head = element('tr');
    ['Cenário', 'Usuários/sem.', 'Perguntas/sem.', 'Custo/sem. (US$)', 'Custo/mês (US$)', 'Custo/resolução (US$)', 'ROI']
      .forEach((label, index) => head.append(element('th', index ? 'num' : '', label)));
    thead.append(head);
    const body = element('tbody');
    data.projection.forEach(row => {
      const tr = element('tr');
      const cells = [row.scenario === 'base' ? 'Base' : 'Pessimista (p95)', num(row.users_per_week),
        row.requests_per_week === null ? 'n/d' : num(row.requests_per_week),
        row.cost_week_usd === null ? 'n/d' : row.cost_week_usd.toFixed(2),
        row.cost_month_usd === null ? 'n/d' : row.cost_month_usd.toFixed(2),
        row.cost_per_resolution_usd === null ? 'n/d' : row.cost_per_resolution_usd.toFixed(4),
        row.roi === null ? 'n/d' : num(row.roi)];
      cells.forEach((value, index) => tr.append(element('td', index ? 'num' : '', value)));
      body.append(tr);
    });
    table.append(thead, body);
    const scroll = element('div', 'mon-table-scroll'); scroll.append(table);
    const ass = data.assumptions;
    const unconfirmed = data.unconfirmed_price_models.join(', ') || 'nenhum';
    const note = element('p', 'mon-note',
      `Premissas: atendimento humano a US$ ${ass.support_cost_per_resolution_usd} (Gartner, 2019) e dólar a R$ ${ass.usd_to_brl} (PTAX do Banco Central). `
      + (ass.questions_per_user_per_week || data.measured_questions_per_user_week
        ? `Perguntas por usuário por semana: ${ass.questions_per_user_per_week || data.measured_questions_per_user_week}. `
        : `Perguntas por usuário por semana: sem medição (${data.observed_days} dia(s) de dados; a taxa precisa de 7 dias ou mais). `)
      + `Pessimista = custo medido no p95. Preço sem confirmação na página oficial: ${unconfirmed}. Fontes no relatório em PDF.`);
    projection.append(projectionHead, scroll, note);

    target.replaceChildren(toolbar, groups, charts, projection);

    if (!window.Plotly) { charts.replaceChildren(element('p', 'chart-error', 'A biblioteca Plotly local não está disponível.')); return; }
    const color = { blue: '#356ce0', light: '#9dbdff', muted: '#6b7580', danger: '#ffb3ad', grid: '#343a3e' };
    const base = (extra = {}) => ({
      paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)', height: 300, autosize: true,
      font: { color: '#a7afb8', family: 'Google Sans Flex, sans-serif', size: 11 },
      margin: { l: 16, r: 16, t: 12, b: 48 }, showlegend: false,
      xaxis: { gridcolor: color.grid, zerolinecolor: color.grid, automargin: true, ...extra.xaxis },
      yaxis: { gridcolor: color.grid, zerolinecolor: color.grid, automargin: true, ...extra.yaxis },
      ...extra.rest,
    });
    const config = { displayModeBar: false, responsive: true };
    // O Plotly não define a altura do contêiner sozinho; sem isso o gráfico fica com altura zero.
    const draw = (id, traces, layout, options) => {
      document.getElementById(id).style.height = `${layout.height + 20}px`;
      return Plotly.newPlot(id, traces, layout, options);
    };
    const empty = id => document.getElementById(id).replaceChildren(element('p', 'neutral-message', 'Sem dados ainda.'));

    const series = data.series;
    if (!series.length) empty('mon-series');
    else {
      const x = series.map((_, index) => index + 1);
      const limit = slo.latency_p95_limit_ms / 1000;
      draw('mon-series', [
        { x, y: series.map(item => item.total_ms / 1000), type: 'scatter', mode: 'lines+markers', line: { color: color.blue, width: 2 },
          marker: { color: color.light, size: 7 }, customdata: series.map(item => new Date(item.at).toLocaleTimeString('pt-BR')),
          hovertemplate: 'Requisição %{x} · %{customdata}<br>%{y:.1f} s<extra></extra>' },
        { x: [Math.min(...x), Math.max(...x, 2)], y: [limit, limit], type: 'scatter', mode: 'lines',
          line: { color: color.danger, width: 1, dash: 'dash' }, hoverinfo: 'skip' },
      ], base({ xaxis: { title: { text: 'Requisição', standoff: 8 }, dtick: series.length > 12 ? undefined : 1 },
        yaxis: { title: { text: 'segundos', standoff: 8 }, rangemode: 'tozero' },
        rest: { annotations: [{ x: 1, xref: 'paper', xanchor: 'right', y: limit, yanchor: 'bottom', showarrow: false,
          text: 'limite do SLO', font: { color: color.danger, size: 10 } }] } }), config);
    }

    const nodes = Object.entries(data.latency_by_node_ms).sort((a, b) => a[1].p95 - b[1].p95);
    if (!nodes.length) empty('mon-nodes');
    else draw('mon-nodes', [
      { y: nodes.map(([name]) => name), x: nodes.map(([, v]) => v.p50 / 1000), type: 'bar', orientation: 'h', name: 'p50', marker: { color: color.light },
        hovertemplate: '%{y} · p50 %{x:.2f} s<extra></extra>' },
      { y: nodes.map(([name]) => name), x: nodes.map(([, v]) => v.p95 / 1000), type: 'bar', orientation: 'h', name: 'p95', marker: { color: color.blue },
        hovertemplate: '%{y} · p95 %{x:.2f} s<extra></extra>' },
    ], base({ xaxis: { title: { text: 'segundos', standoff: 8 } }, rest: { barmode: 'group', showlegend: true,
      legend: { orientation: 'h', x: 1, xanchor: 'right', y: 1.1 }, margin: { l: 16, r: 16, t: 28, b: 48 }, height: Math.max(300, nodes.length * 38 + 80) } }), config);

    const costs = Object.entries(data.cost_by_component_usd).filter(([, value]) => value > 0).sort((a, b) => a[1] - b[1]);
    if (!costs.length) empty('mon-cost');
    else draw('mon-cost', [{ y: costs.map(([name]) => name), x: costs.map(([, value]) => value), type: 'bar', orientation: 'h',
      marker: { color: color.blue }, text: costs.map(([, value]) => `US$ ${value.toFixed(4)}`), textposition: 'outside', cliponaxis: false,
      hovertemplate: '%{y} · US$ %{x:.5f}<extra></extra>' }],
    base({ xaxis: { title: { text: 'US$', standoff: 8 }, range: [0, Math.max(...costs.map(([, v]) => v)) * 1.4] },
      rest: { margin: { l: 16, r: 24, t: 12, b: 48 } } }), config);

    const clients = Object.entries(data.cost_by_client).sort((a, b) => a[1].cost_usd - b[1].cost_usd);
    if (!clients.length) empty('mon-clients');
    else draw('mon-clients', [{ y: clients.map(([name]) => name), x: clients.map(([, v]) => v.cost_usd), type: 'bar', orientation: 'h',
      marker: { color: color.blue }, text: clients.map(([, v]) => `US$ ${v.cost_usd.toFixed(4)} · ${v.requests} req.`), textposition: 'outside', cliponaxis: false,
      hovertemplate: '%{y} · US$ %{x:.5f}<extra></extra>' }],
    base({ xaxis: { title: { text: 'US$', standoff: 8 }, range: [0, Math.max(...clients.map(([, v]) => v.cost_usd)) * 1.7] },
      rest: { margin: { l: 16, r: 24, t: 12, b: 48 } } }), config);

    const results = [['Sucesso', out.success, color.blue], ['Parcial', out.partial, color.light], ['Falha', out.error, color.danger], ['Bloqueada', out.rejected, color.muted]].reverse();
    if (!data.requests) empty('mon-outcomes');
    else draw('mon-outcomes', [{ y: results.map(([name]) => name), x: results.map(([, value]) => value), type: 'bar', orientation: 'h',
      marker: { color: results.map(([, , tone]) => tone) }, text: results.map(([, value]) => String(value)), textposition: 'outside', cliponaxis: false,
      hovertemplate: '%{y} · %{x}<extra></extra>' }],
    base({ xaxis: { title: { text: 'requisições', standoff: 8 }, dtick: 1, range: [0, Math.max(1, ...results.map(([, value]) => value)) * 1.3] } }), config);
  },
};
