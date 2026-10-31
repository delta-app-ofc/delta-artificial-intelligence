from __future__ import annotations

from typing import Any

from app.agents._runtime import AgentResult, run_agent
from app.services.prompts import vazamento_prompt_completo, perfil_bloco
from app.tools.charts import build_leak_chart
from app.tools.leak.tools import build_tools


class LeakAgent:
    def __init__(self, user_id: int, llm: Any = None, access_kind: str | None = None) -> None:
        self.user_id = user_id
        self.access_kind = access_kind
        if llm is None:
            from app.services.llms import llm_especialista

            llm = llm_especialista
        self.llm = llm
        self.tools = build_tools(self.user_id)

    def run(
        self,
        question: str,
        *,
        revision_feedback: str | None = None,
        revision_context: dict | None = None,
    ) -> AgentResult:
        result = run_agent(
            llm=self.llm,
            system_prompt=vazamento_prompt_completo() + perfil_bloco(self.access_kind),
            tools=self.tools,
            question=question,
            revision_feedback=revision_feedback,
            revision_context=revision_context,
        )
        result.chart_data = build_leak_chart(result.tool_calls)
        return result
