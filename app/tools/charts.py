"""Gráficos Plotly montados a partir dos resultados das ferramentas.

Funções determinísticas: só usam números já retornados pelas tools, nunca
valores gerados pelo LLM.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agents._runtime import ToolCall

_LAYOUT = {"height": 300, "margin": {"l": 50, "r": 20, "t": 40, "b": 40}}


def _is_positive(value: object) -> bool:
    """True para número maior que zero; None, texto e zero contam como sem dado."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def build_habits_chart(tool_calls: list[ToolCall]) -> dict | None:
    habits: list[dict] = []
    for tc in tool_calls:
        if tc.name == "list_habits" and isinstance(tc.output, dict):
            habits = tc.output.get("habits") or []
            break

    if not habits:
        return None

    import plotly.graph_objects as go

    names = [h["name"].title() for h in habits]
    freqs = [h["frequency"] for h in habits]

    fig = go.Figure(
        go.Bar(
            x=freqs,
            y=names,
            orientation="h",
            marker_color="#2196F3",
            text=[f"{f}x/sem" for f in freqs],
            textposition="auto",
        )
    )
    fig.update_layout(
        title="Frequência semanal dos hábitos",
        xaxis_title="Vezes por semana",
        yaxis_title="Hábito",
        height=max(250, 60 * len(habits)),
        margin={"l": 150, "r": 20, "t": 40, "b": 40},
    )
    return fig.to_dict()


def build_simulation_chart(tool_calls: list[ToolCall]) -> dict | None:
    """Barras do consumo no período: cenário atual contra o simulado."""
    scenario: dict | None = None
    for tc in tool_calls:
        if tc.name == "simulate_consumption_change" and isinstance(tc.output, dict):
            if tc.output.get("status") == "ok":
                scenario = tc.output.get("scenario")
    if not scenario:
        return None

    import plotly.graph_objects as go

    change = scenario["change_pct"]
    labels = ["Cenário atual", f"Simulado ({change:+g}%)"]
    values = [scenario["base_period_liters"], scenario["scenario_period_liters"]]
    fig = go.Figure(
        go.Bar(x=labels, y=values, marker_color=["#2196F3", "#4CAF50" if change < 0 else "#F44336"],
               text=[f"{v:.0f} L" for v in values], textposition="outside")
    )
    fig.update_layout(
        title=f"Consumo em {scenario['days']} dias: atual x simulado",
        yaxis_title="Litros",
        **_LAYOUT,
    )
    return fig.to_dict()


def _month_summary_chart(forecast: dict) -> dict | None:
    """Barras do mês (consumido, projeção e meta) quando não há série diária para a linha."""
    projection = forecast.get("projection") or {}
    risk = forecast.get("target_risk") or {}
    bars = [
        ("Consumido até hoje", projection.get("month_consumption_so_far_liters"), "#2196F3"),
        ("Projeção do mês", projection.get("month_projection_liters"), "#FF9800"),
        ("Meta do mês", risk.get("monthly_target_liters"), "#4CAF50"),
    ]
    bars = [(label, value, color) for label, value, color in bars if value is not None]
    # A rotina de previsão pode retornar zeros quando não encontrou leituras;
    # isso não é uma série útil para visualização e não deve virar um gráfico
    # aparentemente válido.
    usage_bars = [value for label, value, _ in bars if label != "Meta do mês"]
    if len(bars) < 2 or not any(float(value) > 0 for value in usage_bars):
        return None

    import plotly.graph_objects as go

    fig = go.Figure(
        go.Bar(
            x=[label for label, _, _ in bars],
            y=[value for _, value, _ in bars],
            marker_color=[color for _, _, color in bars],
            text=[f"{value:.0f} L" for _, value, _ in bars],
            textposition="outside",
        )
    )
    fig.update_layout(title="Consumo do mês: atual, projeção e meta", yaxis_title="Litros", **_LAYOUT)
    return fig.to_dict()


def build_forecast_chart(tool_calls: list[ToolCall]) -> dict | None:
    points: list[dict] = []
    forecast: dict | None = None

    for tc in tool_calls:
        if tc.name == "get_consumption_history" and isinstance(tc.output, dict):
            if tc.output.get("status") == "ok":
                points = tc.output.get("windows") or []
        if tc.name == "calculate_forecast" and isinstance(tc.output, dict):
            if tc.output.get("status") == "ok":
                forecast = tc.output.get("forecast") or {}

    # Histórico só com zeros ou sem litros não vira linha de consumo.
    if not any(_is_positive(p.get("consumption_liters")) for p in points):
        points = []

    if not points and not forecast:
        return None

    import plotly.graph_objects as go

    if not points:
        if not forecast.get("has_enough_history"):
            return None
        return _month_summary_chart(forecast)

    fig = go.Figure()

    if points:
        dates = [p.get("window_started_at", "")[:10] for p in points]
        liters = [p.get("consumption_liters", 0) for p in points]
        fig.add_trace(
            go.Scatter(
                x=dates,
                y=liters,
                mode="lines+markers",
                name="Histórico (L)",
                line={"color": "#2196F3"},
            )
        )

    if forecast and forecast.get("has_enough_history"):
        projection = forecast.get("projection") or {}
        proj_liters = projection.get("month_projection_liters")
        bill = forecast.get("bill") or {}
        cost = bill.get("estimated_value")

        lines: list[str] = []
        if proj_liters is not None:
            lines.append(f"Projeção mês: {proj_liters:.0f} L")
        if cost is not None:
            lines.append(f"Estimativa: R$ {float(cost):.2f}")

        if lines:
            fig.add_annotation(
                text="<br>".join(lines),
                xref="paper",
                yref="paper",
                x=0.98,
                y=0.95,
                showarrow=False,
                font={"size": 12},
                align="right",
                bgcolor="rgba(255,255,255,0.8)",
                bordercolor="#cccccc",
                borderwidth=1,
            )

    fig.update_layout(
        title="Histórico de consumo de água",
        xaxis_title="Data",
        yaxis_title="Litros",
        **_LAYOUT,
    )
    return fig.to_dict()


def _window_label(window: dict) -> str:
    """Rótulo curto "16/10 10h-11h" no horário de Brasília."""
    from app.tools.leak.tools import to_local_iso

    start_text = window.get("window_started_at") or ""
    start_local = to_local_iso(start_text)
    if start_local is None:
        return start_text[:10]
    start = datetime.fromisoformat(start_local)
    label = f"{start:%d/%m} {start:%H}h"
    end_local = to_local_iso(window.get("window_ended_at") or "")
    if end_local:
        end = datetime.fromisoformat(end_local)
        # Janela que termina às 00:00:00 ou às 23:59:59.999 é arredondada para a hora cheia.
        end = (end + timedelta(milliseconds=1)).replace(microsecond=0)
        label += f"-{end:%H}h"
    return label


def build_leak_chart(tool_calls: list[ToolCall]) -> dict | None:
    """Gráfico de barras com janelas anômalas por data."""
    windows: list[dict] = []
    for tc in tool_calls:
        if tc.name in ("get_anomalous_windows", "summarize_anomalous_windows"):
            out = tc.output or {}
            if isinstance(out, dict) and out.get("status") == "ok":
                windows = out.get("windows") or []
                break

    # Sem janela com litros registrados não há o que desenhar: melhor sem gráfico do que um vazio.
    windows = [w for w in windows if _is_positive(w.get("consumption_liters"))]
    if not windows:
        return None

    import plotly.graph_objects as go

    labels = [_window_label(w) for w in windows]
    liters = [w.get("consumption_liters", 0) for w in windows]

    fig = go.Figure(
        go.Bar(
            x=labels,
            y=liters,
            marker_color="#F44336",
            name="Janelas anômalas (L)",
            width=0.4,
        )
    )
    # Categoria evita que o Plotly trate o texto como data e estique a barra pelo eixo de tempo.
    fig.update_xaxes(type="category")
    fig.update_layout(
        title="Janelas de consumo anômalo",
        xaxis_title="Horário de Brasília",
        yaxis_title="Litros",
        **_LAYOUT,
    )
    return fig.to_dict()
