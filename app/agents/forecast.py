from __future__ import annotations

from datetime import date
from typing import Any

from app.agents._runtime import AgentResult, ToolCall, run_agent
from app.services.prompts import previsao_prompt_completo
from app.tools.forecast.tools import build_tools
from app.integrations.mcp.weather import get_weather_tools


def _build_forecast_chart(tool_calls: list[ToolCall]) -> dict | None:
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
        height=300,
        margin={"l": 50, "r": 20, "t": 40, "b": 40},
    )
    return fig.to_dict()
from app.agents._runtime import AgentResult, run_agent
from app.services.prompts import previsao_prompt_completo
from app.tools.forecast.tools import build_tools


class ForecastAgent:
    def __init__(self, user_id: int, llm: Any = None, today: date | None = None) -> None:
        self.user_id = user_id
        self.today = today or date.today()
        if llm is None:
            # Import tardio: evita criar cliente de LLM real no import (testes injetam um fake).
            from app.services.llms import llm_especialista

            llm = llm_especialista
        self.llm = llm
        self.tools = build_tools(self.user_id, self.today) + get_weather_tools()

    def run(self, question: str) -> AgentResult:
        result = run_agent(
        self.tools = build_tools(self.user_id, self.today)

    def run(self, question: str) -> AgentResult:
        return run_agent(
            llm=self.llm,
            system_prompt=previsao_prompt_completo(),
            tools=self.tools,
            question=question,
        )
        result.chart_data = _build_forecast_chart(result.tool_calls)
        return result
