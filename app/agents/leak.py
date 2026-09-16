from __future__ import annotations

from typing import Any

from app.agents._runtime import AgentResult, run_agent
from app.services.prompts import VAZAMENTO_PROMPT_COMPLETO
from app.tools.leak.tools import build_tools


class LeakAgent:
    def __init__(self, user_id: int, llm: Any = None) -> None:
        self.user_id = user_id
        if llm is None:
            from app.services.llms import llm_especialista

            llm = llm_especialista
        self.llm = llm
        self.tools = build_tools(self.user_id)

    def run(self, question: str) -> AgentResult:
        return run_agent(
            llm=self.llm,
            system_prompt=VAZAMENTO_PROMPT_COMPLETO,
            tools=self.tools,
            question=question,
        )
