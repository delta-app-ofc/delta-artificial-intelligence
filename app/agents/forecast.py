from __future__ import annotations

from datetime import date
from typing import Any

from app.agents._runtime import AgentResult, ToolCall, run_agent
from app.services.prompts import previsao_prompt_completo
from app.tools.forecast.tools import build_tools
from app.integrations.mcp.weather import WEATHER_TOOLS


def _build_forecast_chart(tool_calls: list[ToolCall]) -> dict | None:
    """Gera gráfico de linha com histórico de consumo e, se disponível, projeção."""
    points: list[dict] = []
    forecast: dict | None = None

    for tc in tool_calls:
        if tc.name == "get_consumption_history" and isinstance(tc.output, dict):
            points = tc.output.get("windows") or []
        if tc.name == "calculate_forecast" and isinstance(tc.output, dict):
            forecast = (tc.output.get("forecast") or {})

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
        proj = forecast.get("projected_month_liters")
        if proj is not None:
            fig.add_annotation(
                text=f"Projeção mês: {proj:.0f} L",
                xref="paper",
                yref="paper",
                x=0.98,
                y=0.95,
                showarrow=False,
                font={"size": 12},
                align="right",
            )

    fig.update_layout(
        title="Histórico de consumo de água",
        xaxis_title="Data",
        yaxis_title="Litros",
        height=300,
        margin={"l": 50, "r": 20, "t": 40, "b": 40},
    )
    return fig.to_dict()


class ForecastAgent:
    def __init__(self, user_id: int, llm: Any = None, today: date | None = None) -> None:
        self.user_id = user_id
        self.today = today or date.today()
        if llm is None:
            from app.services.llms import llm_especialista

            llm = llm_especialista
        self.llm = llm
        self.tools = build_tools(self.user_id, self.today) + WEATHER_TOOLS

    def run(self, question: str) -> AgentResult:
        result = run_agent(
            llm=self.llm,
            system_prompt=previsao_prompt_completo(),
            tools=self.tools,
            question=question,
        )
        result.chart_data = _build_forecast_chart(result.tool_calls)
        return result
