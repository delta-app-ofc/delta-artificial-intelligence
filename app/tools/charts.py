"""Gráficos Plotly montados a partir dos resultados das ferramentas.

Funções determinísticas: só usam números já retornados pelas tools, nunca
valores gerados pelo LLM.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agents._runtime import ToolCall

_LAYOUT = {"height": 300, "margin": {"l": 50, "r": 20, "t": 40, "b": 40}}


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


def build_forecast_chart(tool_calls: list[ToolCall]) -> dict | None:
    points: list[dict] = []
    forecast: dict | None = None

    for tc in tool_calls:
        if tc.name == "get_consumption_history" and isinstance(tc.output, dict):
            points = tc.output.get("windows") or []
        if tc.name == "calculate_forecast" and isinstance(tc.output, dict):
            forecast = tc.output.get("forecast") or {}

    if not points and not forecast:
        return None

    import plotly.graph_objects as go

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

    if forecast:
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


def build_leak_chart(tool_calls: list[ToolCall]) -> dict | None:
    """Gráfico de barras com janelas anômalas por data."""
    windows: list[dict] = []
    for tc in tool_calls:
        if tc.name in ("get_anomalous_windows", "summarize_anomalous_windows"):
            out = tc.output or {}
            if isinstance(out, dict):
                windows = out.get("windows") or []
                break

    if not windows:
        return None

    import plotly.graph_objects as go

    dates = [w.get("window_started_at", "")[:10] for w in windows]
    liters = [w.get("consumption_liters", 0) for w in windows]

    fig = go.Figure(
        go.Bar(
            x=dates,
            y=liters,
            marker_color="#F44336",
            name="Janelas anômalas (L)",
        )
    )
    fig.update_layout(
        title="Janelas de consumo anômalo",
        xaxis_title="Data",
        yaxis_title="Litros",
        **_LAYOUT,
    )
    return fig.to_dict()
