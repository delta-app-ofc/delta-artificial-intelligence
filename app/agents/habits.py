from __future__ import annotations

from typing import Any

from app.agents._runtime import AgentResult, run_agent
from app.services.prompts import habitos_prompt_completo
from app.tools.charts import build_habits_chart
from app.tools.habits.tools import build_tools


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
            system_prompt=habitos_prompt_completo(),
            tools=self.tools,
            question=question,
        )
        result.chart_data = build_habits_chart(result.tool_calls)
        return result
