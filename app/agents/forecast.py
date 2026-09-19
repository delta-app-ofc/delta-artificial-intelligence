from __future__ import annotations

from datetime import date
from typing import Any

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
        self.tools = build_tools(self.user_id, self.today)

    def run(self, question: str) -> AgentResult:
        return run_agent(
            llm=self.llm,
            system_prompt=previsao_prompt_completo(),
            tools=self.tools,
            question=question,
        )
