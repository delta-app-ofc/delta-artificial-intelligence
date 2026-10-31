"""Gera o relatório de observabilidade em PDF, no estilo do relatório gerencial de BI do Delta.

O relatório não inclui prompts, respostas nem dados pessoais. A paleta (fundo azul-noturno,
cartões, azul e ciano) e a organização (cabeçalho, indicadores por tema, painéis) seguem o
relatório de BI e o console de testes para os três se parecerem.
"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    BaseDocTemplate, Flowable, Frame, KeepTogether, PageTemplate, Paragraph, Spacer, Table, TableStyle,
)

from app.config import BASE_DIR
from app.observability.metrics import project

# Paleta do relatório gerencial de BI do Delta.
BG = colors.HexColor("#080b10")
SURFACE = colors.HexColor("#151e2b")
LINE = colors.HexColor("#2b3b51")
TEXT = colors.HexColor("#f5f7fb")
MUTED = colors.HexColor("#c9d1dd")
BLUE = colors.HexColor("#2f7bff")
BLUE_LIGHT = colors.HexColor("#6ea8ff")
CYAN = colors.HexColor("#10bceb")
GREEN = colors.HexColor("#35c978")
DANGER = colors.HexColor("#ff9b94")
GRAY = colors.HexColor("#6b7a90")

PAGE_W, PAGE_H = A4
MARGIN = 1.6 * cm
CONTENT_W = PAGE_W - 2 * MARGIN
LOGO = BASE_DIR / "frontend" / "assets" / "delta-drop.png"

_BODY = ParagraphStyle("body", fontName="Helvetica", fontSize=8, leading=11.5, textColor=MUTED, alignment=TA_LEFT)
_TITLE = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=26, leading=30, textColor=TEXT)
_TITLE_ACCENT = ParagraphStyle("title_accent", parent=_TITLE, textColor=CYAN)
_SUBTITLE = ParagraphStyle("subtitle", fontName="Helvetica", fontSize=9.5, leading=13, textColor=MUTED)
_EYEBROW = ParagraphStyle("eyebrow", fontName="Helvetica-Bold", fontSize=7, leading=10, textColor=BLUE_LIGHT)

_TONES = {"ok": GREEN, "bad": DANGER, "": TEXT}


def _fmt(value) -> str:
    return "n/d" if value is None else str(value)


def _usd(value) -> str:
    return "n/d" if value is None else f"US$ {float(value):.4f}"


def _pct(value) -> str:
    return f"{value * 100:.1f}%"


def _secs(ms: float) -> str:
    return f"{ms / 1000:.1f} s" if ms >= 1000 else f"{round(ms)} ms"


def _num(value) -> str:
    return f"{value:,}".replace(",", ".")


def _round_rect(canvas: Canvas, x, y, w, h, fill=SURFACE, stroke=LINE, radius=8) -> None:
    canvas.setFillColor(fill)
    canvas.setStrokeColor(stroke)
    canvas.setLineWidth(0.6)
    canvas.roundRect(x, y, w, h, radius, stroke=1, fill=1)


class _Card(Flowable):
    """Cartão de indicador, igual aos cartões do Monitor."""

    def __init__(self, label: str, value: str, hint: str = "", tone: str = "") -> None:
        super().__init__()
        self.label, self.value, self.hint, self.tone = label, value, hint, tone
        self.height = 56

    def wrap(self, avail_w, avail_h):
        self.width = avail_w
        return avail_w, self.height

    def draw(self) -> None:
        c = self.canv
        _round_rect(c, 0, 0, self.width, self.height, stroke=DANGER if self.tone == "bad" else LINE, radius=9)
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 7)
        c.drawString(10, self.height - 15, self.label)
        c.setFillColor(_TONES.get(self.tone, TEXT))
        c.setFont("Helvetica-Bold", 14.5)
        c.drawString(10, self.height - 33, self.value)
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 6.2)
        c.drawString(10, 8, self.hint[:48])


class _Panel(Flowable):
    """Painel com cabeçalho (título à esquerda, etiqueta azul à direita) e corpo desenhado pela subclasse."""

    header = 26

    def __init__(self, title: str, tag: str, body_height: float) -> None:
        super().__init__()
        self.title, self.tag, self.body_height = title, tag, body_height

    def wrap(self, avail_w, avail_h):
        self.width = avail_w
        self.height = self.header + self.body_height
        return avail_w, self.height

    def draw(self) -> None:
        c = self.canv
        _round_rect(c, 0, 0, self.width, self.height, radius=10)
        c.setStrokeColor(LINE)
        c.line(0, self.body_height, self.width, self.body_height)
        c.setFillColor(TEXT)
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(12, self.body_height + 9, self.title)
        c.setFillColor(CYAN)
        c.setFont("Helvetica-Bold", 6)
        c.drawRightString(self.width - 12, self.body_height + 10, self.tag)
        self.draw_body(c, 12, 8, self.width - 24, self.body_height - 14)

    def draw_body(self, c: Canvas, x: float, y: float, w: float, h: float) -> None:
        raise NotImplementedError

    def empty(self, c: Canvas, x: float, y: float, h: float) -> None:
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 8)
        c.drawString(x, y + h / 2, "Sem dados ainda.")


class _BarPanel(_Panel):
    """Barras horizontais; cada linha tem uma ou mais barras (ex.: p50 e p95)."""

    def __init__(self, title, tag, rows, unit="", legend=None, bar_h=8, gap=8):
        # rows: [(rótulo, [(valor, cor, texto)])]
        self.rows, self.unit, self.legend, self.bar_h, self.gap = rows, unit, legend or [], bar_h, gap
        per_row = max((len(series) for _, series in rows), default=1)
        self.row_h = per_row * (bar_h + 2) + gap
        super().__init__(title, tag, max(60, len(rows) * self.row_h + 26 + (14 if legend else 0)))

    def draw_body(self, c, x, y, w, h):
        if not self.rows:
            return self.empty(c, x, y, h)
        top = y + h
        if self.legend:
            lx = x + w
            c.setFont("Helvetica", 6.5)
            for name, tone in reversed(self.legend):
                lx -= c.stringWidth(name, "Helvetica", 6.5) + 4
                c.setFillColor(MUTED)
                c.drawString(lx, top - 2, name)
                lx -= 8
                c.setFillColor(tone)
                c.rect(lx, top - 2, 6, 6, stroke=0, fill=1)
                lx -= 8
            top -= 14
        label_w = 78
        value_w = 52
        bar_x = x + label_w
        max_w = w - label_w - value_w
        biggest = max((v for _, series in self.rows for v, _, _ in series), default=0) or 1
        for index, (label, series) in enumerate(self.rows):
            row_top = top - index * self.row_h
            c.setFillColor(MUTED)
            c.setFont("Helvetica", 7)
            c.drawRightString(bar_x - 6, row_top - self.bar_h - 0.5, label[:18])
            for k, (value, tone, text) in enumerate(series):
                by = row_top - (k + 1) * (self.bar_h + 2) + 2
                width = max(1.2, max_w * value / biggest) if value > 0 else 0
                c.setFillColor(tone)
                if width:
                    c.roundRect(bar_x, by, width, self.bar_h, 1.5, stroke=0, fill=1)
                c.setFillColor(MUTED)
                c.setFont("Helvetica", 6.3)
                c.drawString(bar_x + width + 4, by + 1.5, text)


class _LinePanel(_Panel):
    """Tempo total por requisição, com a linha tracejada do limite do SLO."""

    def __init__(self, title, tag, values, limit):
        self.values, self.limit = values, limit
        super().__init__(title, tag, 150)

    def draw_body(self, c, x, y, w, h):
        if not self.values:
            return self.empty(c, x, y, h)
        left, bottom = 30, 16
        px, py, pw, ph = x + left, y + bottom, w - left - 8, h - bottom - 6
        top = max(max(self.values), self.limit) * 1.15
        c.setFont("Helvetica", 6.3)
        for step in range(5):
            gy = py + ph * step / 4
            c.setStrokeColor(LINE)
            c.setLineWidth(0.4)
            c.line(px, gy, px + pw, gy)
            c.setFillColor(MUTED)
            c.drawRightString(px - 4, gy - 2, f"{top * step / 4:.0f}s")
        count = len(self.values)

        def at(index):
            return px + (pw * index / (count - 1) if count > 1 else pw / 2)

        limit_y = py + ph * self.limit / top
        c.setStrokeColor(DANGER)
        c.setLineWidth(0.8)
        c.setDash(3, 3)
        c.line(px, limit_y, px + pw, limit_y)
        c.setDash()
        c.setFillColor(DANGER)
        c.drawRightString(px + pw, limit_y + 3, "limite do SLO")
        points = [(at(i), py + ph * v / top) for i, v in enumerate(self.values)]
        c.setStrokeColor(BLUE)
        c.setLineWidth(1.4)
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            c.line(x1, y1, x2, y2)
        c.setFillColor(CYAN)
        for (point_x, point_y) in points:
            c.circle(point_x, point_y, 2.4, stroke=0, fill=1)
        c.setFillColor(MUTED)
        every = max(1, count // 10)
        for i in range(0, count, every):
            c.drawCentredString(at(i), py - 11, str(i + 1))


def _decorate(canvas: Canvas, doc) -> None:
    canvas.saveState()
    canvas.setFillColor(BG)
    canvas.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
    canvas.setFillColor(BLUE_LIGHT)
    canvas.setFont("Helvetica-Bold", 15)
    canvas.drawString(MARGIN, PAGE_H - MARGIN - 8, "Delta")
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 6.5)
    canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - MARGIN - 7, "INTELIGÊNCIA DE NEGÓCIOS · RELATÓRIO DE OBSERVABILIDADE")
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.5)
    canvas.line(0, PAGE_H - MARGIN - 20, PAGE_W, PAGE_H - MARGIN - 20)
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN, MARGIN - 4, PAGE_W - MARGIN, MARGIN - 4)
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 6.5)
    canvas.drawString(MARGIN, MARGIN - 15, "Delta · Relatório de observabilidade da IA")
    canvas.drawRightString(PAGE_W - MARGIN, MARGIN - 15, f"Página {doc.page}")
    canvas.restoreState()


def _section(title: str) -> Paragraph:
    return Paragraph(escape(title.upper()), ParagraphStyle("section", parent=_EYEBROW, spaceBefore=12, spaceAfter=6))


def _card_grid(cards: list[_Card], columns: int = 4) -> Table:
    rows = [cards[i:i + columns] for i in range(0, len(cards), columns)]
    for row in rows:
        row.extend([""] * (columns - len(row)))
    table = Table(rows, colWidths=[CONTENT_W / columns] * columns)
    table.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return table


def _styled_table(rows: list[list], widths: list[float], right_from: int = 1) -> Table:
    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1b283a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), MUTED), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 6.5),
        ("TEXTCOLOR", (0, 1), (-1, -1), TEXT), ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("ALIGN", (right_from, 0), (-1, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINE),
        ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("ROUNDEDCORNERS", [9, 9, 9, 9]),
    ]))
    return table


def build_pdf(summary: dict) -> bytes:
    buffer = BytesIO()
    doc = BaseDocTemplate(buffer, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN + 34,
                          bottomMargin=MARGIN + 6, title="Relatório de observabilidade Delta AI", author="Delta")
    doc.addPageTemplates([PageTemplate(id="main", onPage=_decorate, frames=[
        Frame(MARGIN, MARGIN + 6, CONTENT_W, PAGE_H - 2 * MARGIN - 34, leftPadding=0, rightPadding=0,
              topPadding=0, bottomPadding=0)])])

    measured = summary["requests"] > 0
    slo = summary["slo"]
    lat = summary["latency_total_ms"]
    out = summary["outcomes"]
    error_tone = "" if not measured else "ok" if summary["error_rate"] <= slo["error_rate_limit"] else "bad"
    slo_tone = "" if slo["ok"] is None else "ok" if slo["ok"] else "bad"
    slo_text = "SLO sem dados" if slo["ok"] is None else "SLO atendido" if slo["ok"] else "SLO violado"

    story: list = [
        Paragraph("ÁGUA, DADOS E CONTEXTO", _EYEBROW), Spacer(1, 6),
        Paragraph("Custo, latência e retorno.", _TITLE),
        Paragraph("Decisões com contexto.", _TITLE_ACCENT), Spacer(1, 6),
        Paragraph(f"Gerado em {datetime.now().strftime('%d/%m/%Y às %H:%M')} · "
                  f"{_num(summary['requests'])} requisições analisadas", _SUBTITLE),
    ]
    if not measured:
        story += [Spacer(1, 10), _Card("Sem requisições medidas", "Valores estimados", "premissas, não uso real", "bad"),
                  Spacer(1, 4)]
    else:
        story += [
            _section("Confiabilidade"),
            _card_grid(columns=5, cards=[
                _Card("Índice de erros", _pct(summary["error_rate"]), f"limite {_pct(slo['error_rate_limit'])}", error_tone),
                _Card("Sucesso", _num(out["success"]), f"{_num(out['partial'])} parciais"),
                _Card("Falhas", _num(out["error"]), "requisições com erro", "bad" if out["error"] else ""),
                _Card("Bloqueios", _num(out["rejected"]), "guardrail ou Juiz"),
                _Card("Fallbacks", _num(summary["fallback_calls"]), "chamadas ao modelo reserva"),
            ]),
            _section("Latência"),
            _card_grid([
                _Card("Tempo total p95", _secs(lat["p95"]), f"limite {_secs(slo['latency_p95_limit_ms'])} · {slo_text}", slo_tone),
                _Card("Mediana (p50)", _secs(lat["p50"]), f"média {_secs(lat['avg'])}"),
                _Card("Pior caso (p99)", _secs(lat["p99"])),
                _Card("Orquestração", _secs(summary["overhead_ms"]["p50"]), "tempo entre etapas (p50)"),
            ]),
            _section("Custo"),
            _card_grid([
                _Card("Custo total", _usd(summary["cost_usd"]),
                      f"{_num(summary['usage']['input_tokens'])} tokens de entrada · {_num(summary['usage']['output_tokens'])} de saída"),
                _Card("Custo por requisição", _usd(summary["cost_per_request_usd"]),
                      f"{_num(summary['volume_per_request'])} tokens em média"),
                _Card("Chamadas ao modelo", str(summary["model_calls_per_request"]), "por requisição"),
                _Card("Revisões do Juiz", _pct(summary["revision_rate"]), "requisições com correção"),
                _Card("Embeddings", _usd(summary["embedding_cost_usd"]),
                      f"{_num(summary['usage']['embedding_tokens'])} tokens estimados"),
                _Card("Jev", _usd(summary["jev_cost_usd"]), "custo configurado por avaliação"),
            ]),
            _section("Uso"),
            _card_grid([
                _Card("Usuários distintos", _num(summary["distinct_users"]) if summary["distinct_users"] else "n/d",
                      "no período analisado" if summary["distinct_users"] else "defina OBS_HASH_SECRET"),
                _Card("Perguntas por usuário", _fmt(summary["questions_per_user"]), "medido, não cenário"),
                _Card("Cliente que mais gasta", next(iter(summary["cost_by_client"]), "n/d"),
                      _usd(next(iter(summary["cost_by_client"].values()))["cost_usd"]) if summary["cost_by_client"] else ""),
            ]),
            _section("Retorno"),
            _card_grid([
                _Card("Taxa de resolução", _pct(summary["resolution_rate"]), f"{_num(summary['resolutions'])} resoluções"),
                _Card("Custo por resolução", _usd(summary["cost_per_resolution_usd"])),
                _Card("ROI", _fmt(summary["roi"]), "retorno sobre o custo de IA"),
                _Card("Economia estimada", _usd(summary["savings_usd"]), "atendimentos evitados menos custo"),
            ]),
            Spacer(1, 12),
        ]

        limit = slo["latency_p95_limit_ms"] / 1000
        story.append(KeepTogether([_LinePanel("Tempo total por requisição", "LATÊNCIA",
                                              [item["total_ms"] / 1000 for item in summary["series"]], limit), Spacer(1, 10)]))
        nodes = sorted(summary["latency_by_node_ms"].items(), key=lambda kv: kv[1]["p95"], reverse=True)
        story.append(KeepTogether([_BarPanel(
            "Latência por etapa", "P50 · P95",
            [(name, [(v["p50"] / 1000, CYAN, f"p50 {v['p50'] / 1000:.2f} s"), (v["p95"] / 1000, BLUE, f"p95 {v['p95'] / 1000:.2f} s")])
             for name, v in nodes], legend=[("p50", CYAN), ("p95", BLUE)], bar_h=6, gap=6), Spacer(1, 10)]))
        agents = sorted(summary["latency_by_agent_ms"].items(), key=lambda kv: kv[1]["p95"], reverse=True)
        if agents:
            story.append(KeepTogether([_BarPanel(
                "Latência por agente", "P50 · P95",
                [(name, [(v["p50"] / 1000, CYAN, f"p50 {v['p50'] / 1000:.2f} s"), (v["p95"] / 1000, BLUE, f"p95 {v['p95'] / 1000:.2f} s")])
                 for name, v in agents], legend=[("p50", CYAN), ("p95", BLUE)], bar_h=6, gap=6), Spacer(1, 10)]))
        costs = [(n, v) for n, v in summary["cost_by_component_usd"].items() if v > 0]
        story.append(KeepTogether([_BarPanel("Custo por componente", "USD",
                                             [(n, [(v, BLUE, f"US$ {v:.4f}")]) for n, v in costs], bar_h=9), Spacer(1, 10)]))
        clients = sorted(summary["cost_by_client"].items(), key=lambda kv: kv[1]["cost_usd"], reverse=True)
        story.append(KeepTogether([_BarPanel("Custo por cliente", "APP · WEB",
                                             [(n, [(v["cost_usd"], BLUE, f"US$ {v['cost_usd']:.4f} · {v['requests']} req.")])
                                              for n, v in clients], bar_h=9), Spacer(1, 10)]))
        story.append(KeepTogether([_BarPanel("Resultado das requisições", "ERROS", [
            ("Sucesso", [(out["success"], BLUE, str(out["success"]))]),
            ("Parcial", [(out["partial"], CYAN, str(out["partial"]))]),
            ("Falha", [(out["error"], DANGER, str(out["error"]))]),
            ("Bloqueada", [(out["rejected"], GRAY, str(out["rejected"]))]),
        ], bar_h=9), Spacer(1, 10)]))

    rows = [["CENÁRIO", "USUÁRIOS/SEM.", "PERGUNTAS/SEM.", "CUSTO/SEM. (US$)", "CUSTO/MÊS (US$)", "CUSTO/RESOLUÇÃO", "ROI"]]
    for row in project(summary):
        rows.append(["Base" if row["scenario"] == "base" else "Pessimista", _num(row["users_per_week"]),
                     _num(row["requests_per_week"]), f"{row['cost_week_usd']:.2f}", f"{row['cost_month_usd']:.2f}",
                     "n/d" if row["cost_per_resolution_usd"] is None else f"{row['cost_per_resolution_usd']:.4f}",
                     "n/d" if row["roi"] is None else _num(row["roi"])])
    w = CONTENT_W
    story += [KeepTogether([_section("Projeção para 100 e 1000 usuários por semana"),
                            _styled_table(rows, [w * 0.14, w * 0.14, w * 0.15, w * 0.15, w * 0.15, w * 0.17, w * 0.10]),
                            Spacer(1, 10)])]

    ass = summary["assumptions"]
    sources = "; ".join(f"{m}: {v['url']} ({v['kind']})" for m, v in summary["price_sources"].items())
    notes = [
        "Resolução = resposta publicada sem erro e sem bloqueio do Juiz. Índice de erros = requisições com falha ÷ total. "
        "ROI = (resoluções × custo de um atendimento − custo de IA) ÷ custo de IA.",
        f"Premissas: atendimento humano = US$ {ass['support_cost_per_resolution_usd']}; "
        f"{ass['questions_per_user_per_week']} perguntas por usuário por semana (cenário, sem fonte); US$ 1 = R$ {ass['usd_to_brl']}; "
        f"Jev = US$ {ass['jev_cost_per_evaluation_usd']} por avaliação. Cenário pessimista = custo × 1,5.",
        f"Preços por modelo (tarifa Standard) e fontes: {sources}. Sem confirmação na página oficial: "
        + (", ".join(summary["unconfirmed_price_models"]) or "nenhum") + ". Sem preço cadastrado: "
        + (", ".join(summary["unpriced_models"]) or "nenhum") + ".",
        "Custo de atendimento humano: faixa de referência de US$ 6 a 12 por contato, mediana de US$ 13,50 nos EUA "
        "(Gartner, citado em stealthagents.com); são fontes de mercado, não dados da Delta.",
        "O ROI considera só o custo de tokens dos modelos; hospedagem, bancos, desenvolvimento e manutenção não entram, "
        "então ele é um limite superior. Embeddings não entram no custo.",
    ]
    story += [_section("Definições e premissas")] + [Paragraph(escape(note), _BODY) for note in notes]
    doc.build(story)
    return buffer.getvalue()
