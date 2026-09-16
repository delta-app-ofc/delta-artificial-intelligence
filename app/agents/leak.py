"""Agente de Vazamento — standalone.

Este arquivo é só a "cola": pega o prompt, pega as tools prontas (definidas em
app/tools/leak/tools.py, não aqui) e roda o laço de tool-calling
(app/agents/_runtime.py). Identifica INDÍCIOS de vazamento a partir de sinais
que o motor de detecção (repositório delta-business-rules) já calculou —
nunca inventa limiar ou padrão, nunca dá diagnóstico definitivo.
"""

from __future__ import annotations

from typing import Any

from app.agents._runtime import AgentResult, run_agent
from app.services.prompts import VAZAMENTO_PROMPT_COMPLETO
from app.tools.leak.tools import build_tools


class LeakAgent:
    """Standalone, mesmas garantias do ForecastAgent. Só usa tools de MongoDB."""

    def __init__(self, user_id: int, llm: Any = None) -> None:
        self.user_id = user_id
        if llm is None:
            from app.services.llms import llm_especialista

            llm = llm_especialista
        self.llm = llm
        self.tools = build_tools(self.user_id)

    def run(self, question: str) -> AgentResult:
        """Responde question e devolve texto final + registro de tools."""
        return run_agent(
            llm=self.llm,
            system_prompt=VAZAMENTO_PROMPT_COMPLETO,
            tools=self.tools,
            question=question,
        )
