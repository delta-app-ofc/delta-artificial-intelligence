"""Gera o relatório de observabilidade em PDF, sem prompts, respostas nem dados pessoais."""
from __future__ import annotations

from datetime import datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.observability.metrics import project

_LAT_KEYS = ("avg", "p50", "p95", "p99")


def _table(rows: list[list], widths=None) -> Table:
    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#356ce0")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#eef3fd")]),
    ]))
    return table


def _fmt(value) -> str:
    return "n/d" if value is None else str(value)


def build_pdf(summary: dict) -> bytes:
    styles = getSampleStyleSheet()
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=2 * cm, bottomMargin=2 * cm,
                            title="Relatório de observabilidade Delta AI")
    story = [
        Paragraph("Delta AI · Relatório de observabilidade", styles["Title"]),
        Paragraph(f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')} · "
                  f"{summary['requests']} requisições analisadas", styles["Normal"]),
        Spacer(1, 12),
    ]

    measured = summary["requests"] > 0
    if measured:
        slo = summary["slo"]
        lat = summary["latency_total_ms"]
        story += [Paragraph("1. Resumo e SLO", styles["Heading2"]), _table([
            ["Indicador", "Valor", "Limite"],
            ["Latência total p95 (ms)", lat["p95"], slo["latency_p95_limit_ms"]],
            ["Índice de erros", f"{summary['error_rate'] * 100:.2f}%", f"{slo['error_rate_limit'] * 100:.0f}%"],
            ["SLO", "sem dados" if slo["ok"] is None else "atendido" if slo["ok"] else "violado", ""],
            ["Taxa de resolução", f"{summary['resolution_rate'] * 100:.1f}%", ""],
            ["Custo por resolução (USD)", _fmt(summary["cost_per_resolution_usd"]), ""],
            ["ROI", _fmt(summary["roi"]), "> 0 é retorno positivo"],
            ["Custo total (USD)", summary["cost_usd"], ""],
            ["Custo por requisição (USD)", summary["cost_per_request_usd"], ""],
            ["Tokens por requisição", summary["volume_per_request"], ""],
            ["Chamadas ao modelo por requisição", summary["model_calls_per_request"], ""],
            ["Requisições com revisão do Juiz", f"{summary['revision_rate'] * 100:.1f}%", ""],
            ["Chamadas ao modelo reserva (fallback)", summary["fallback_calls"], ""],
            ["Economia estimada (USD)", summary["savings_usd"], "atendimentos evitados − custo de IA"],
        ], [8 * cm, 4 * cm, 5 * cm]), Spacer(1, 10)]

        latency_rows = [["Etapa / agente", "média", "p50", "p95", "p99"],
                        ["Tempo total", *[lat[k] for k in _LAT_KEYS]],
                        ["Orquestração (entre etapas)", *[summary["overhead_ms"][k] for k in _LAT_KEYS]]]
        latency_rows += [[f"Etapa {name}", *[v[k] for k in _LAT_KEYS]]
                         for name, v in summary["latency_by_node_ms"].items()]
        latency_rows += [[f"Agente {name}", *[v[k] for k in _LAT_KEYS]]
                         for name, v in summary["latency_by_agent_ms"].items()]
        story += [Paragraph("2. Latência (ms)", styles["Heading2"]), _table(latency_rows), Spacer(1, 10)]

        cost_rows = [["Componente", "Custo (USD)"]] + [[n, v] for n, v in summary["cost_by_component_usd"].items()]
        story += [Paragraph("3. Custo por componente", styles["Heading2"]), _table(cost_rows), Spacer(1, 10)]

        out = summary["outcomes"]
        story += [Paragraph("4. Resultado das requisições", styles["Heading2"]), _table([
            ["Sucesso", "Parcial", "Erro", "Bloqueada"],
            [out["success"], out["partial"], out["error"], out["rejected"]]]), Spacer(1, 10)]

    else:
        story += [Paragraph("Sem requisições medidas: os valores abaixo são estimativas baseadas em premissas, não em uso real.", styles["Normal"]), Spacer(1, 10)]

    rows = [["Cenário", "Usuários/sem.", "Perguntas/sem.", "Custo/sem. USD", "Custo/mês USD",
             "Custo/sem. BRL", "Custo/resolução", "ROI"]]
    for row in project(summary):
        rows.append([row["scenario"], row["users_per_week"], row["requests_per_week"], row["cost_week_usd"],
                     row["cost_month_usd"], row["cost_week_brl"], _fmt(row["cost_per_resolution_usd"]),
                     _fmt(row["roi"])])
    story += [Paragraph("5. Projeção para 100 e 1000 usuários semanais", styles["Heading2"]),
              _table(rows), Spacer(1, 10)]

    ass = summary["assumptions"]
    notes = [
        "Resolução = resposta publicada sem erro e sem bloqueio do Juiz. Índice de erros = requisições com falha ÷ total.",
        "ROI = (resoluções × custo de um atendimento − custo de IA) ÷ custo de IA.",
        f"Premissas: atendimento = US$ {ass['support_cost_per_resolution_usd']}; "
        f"{ass['questions_per_user_per_week']} perguntas/usuário/semana; US$ 1 = R$ {ass['usd_to_brl']}; "
        f"Jev = US$ {ass['jev_cost_per_evaluation_usd']} por avaliação. Cenário pessimista = custo × 1,5.",
        "Preço por modelo é tabela fixa (tarifa Standard) e pode divergir da fatura. Fontes: "
        + "; ".join(f"{m}: {v['url']} ({v['kind']})" for m, v in summary["price_sources"].items())
        + ". Sem preço cadastrado: " + (", ".join(summary["unpriced_models"]) or "nenhum") + ".",
        "Custo de atendimento humano: faixa de referência de US$ 6 a 12 por contato, com mediana de "
        "US$ 13,50 nos EUA (Gartner, citado em stealthagents.com); são fontes de mercado, não dados da Delta.",
        "O ROI considera só o custo de tokens dos modelos; hospedagem, bancos, desenvolvimento e manutenção não entram, "
        "então ele é um limite superior.",
        "Embeddings não entram no custo. Dados de testes/mock não representam uso real.",
    ]
    story += [Paragraph("6. Definições e premissas", styles["Heading2"])]
    story += [Paragraph("• " + note, styles["Normal"]) for note in notes]
    doc.build(story)
    return buffer.getvalue()
