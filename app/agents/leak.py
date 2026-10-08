from __future__ import annotations

from typing import Any

from app.agents._runtime import AgentResult, ToolCall, run_agent
from app.services.prompts import vazamento_prompt_completo
from app.tools.leak.tools import build_tools
from app.integrations.mcp.weather import get_weather_tools


def _build_leak_chart(tool_calls: list[ToolCall]) -> dict | None:
    """Gera gráfico de barras com janelas anômalas por data."""
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
        height=300,
        margin={"l": 50, "r": 20, "t": 40, "b": 40},
    )
    return fig.to_dict()


class LeakAgent:
    def __init__(self, user_id: int, llm: Any = None) -> None:
        self.user_id = user_id
        if llm is None:
            from app.services.llms import llm_especialista

            llm = llm_especialista
        self.llm = llm
        self.tools = build_tools(self.user_id) + get_weather_tools()

    def run(self, question: str) -> AgentResult:
        result = run_agent(
            llm=self.llm,
            system_prompt=vazamento_prompt_completo(),
            tools=self.tools,
            question=question,
        )
        result.chart_data = _build_leak_chart(result.tool_calls)
        return result
