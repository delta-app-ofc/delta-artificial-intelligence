from __future__ import annotations

from typing import Any

from app.agents._runtime import AgentResult, run_agent
from app.config import get_settings
from app.services.prompts import HABIT_REGISTRATION_INTERRUPT_PROMPT, full_habits_prompt, profile_block
from app.tools.charts import build_habits_chart
from app.tools.habits.tools import build_tools


class HabitsAgent:
    def __init__(self, user_id: int, llm: Any = None, access_kind: str | None = None) -> None:
        """Cria o agente de hábitos para `user_id`; `access_kind` evita reconsultar o perfil da
        conta.
        """
        self.user_id = user_id
        self.access_kind = access_kind
        if llm is None:
            from app.services.llms import llm_especialista

            llm = llm_especialista
        self.llm = llm
        self.tools = build_tools(self.user_id, access_kind)

    def run(
        self,
        question: str,
        *,
        revision_feedback: str | None = None,
        revision_context: dict | None = None,
    ) -> AgentResult:
        is_revision = bool(revision_feedback or revision_context)
        interrupt = get_settings().confirmation_interrupt_enabled
        # Com a pausa ligada a gravação já ocorreu; sem ela, create_habit só prepara a ação.
        tools = [t for t in self.tools if t.name != "create_habit"] if is_revision and interrupt else self.tools
        prompt = full_habits_prompt() + profile_block(self.access_kind)
        if not is_revision and interrupt:
            prompt += "\n\n" + HABIT_REGISTRATION_INTERRUPT_PROMPT
        result = run_agent(
            llm=self.llm,
            system_prompt=prompt,
            tools=tools,
            question=question,
            revision_feedback=revision_feedback,
            revision_context=revision_context,
        )
        result.chart_data = build_habits_chart(result.tool_calls)
        return result
