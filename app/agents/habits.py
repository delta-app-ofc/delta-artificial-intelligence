from __future__ import annotations

from typing import Any

from app.agents._runtime import AgentResult, ToolCall, run_agent
from app.services.prompts import HABITOS_PROMPT_COMPLETO
from app.tools.habits.tools import build_tools


def _build_habits_chart(tool_calls: list[ToolCall]) -> dict | None:
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


class HabitsAgent:
    def __init__(self, user_id: int, llm: Any = None) -> None:
        self.user_id = user_id
        if llm is None:
            from app.services.llms import llm_especialista

            llm = llm_especialista
        self.llm = llm
        self.tools = build_tools(self.user_id)

    def run(self, question: str) -> AgentResult:
        result = run_agent(
            llm=self.llm,
            system_prompt=HABITOS_PROMPT_COMPLETO,
            tools=self.tools,
            question=question,
        )
        result.chart_data = _build_habits_chart(result.tool_calls)
        return result
