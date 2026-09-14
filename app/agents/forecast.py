"""Agente de Previsão (Agente 3 da arquitetura) — standalone.

Este arquivo é só a "cola": pega o prompt, pega as tools prontas (definidas em
app/tools/forecast/tools.py, não aqui) e roda o laço de tool-calling
(app/agents/_runtime.py). Standalone: sem LangGraph, sem FastAPI, sem chamar
outros agentes. Importável e testável isoladamente —
ForecastAgent(user_id, llm=<fake>) nos testes.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.agents._runtime import AgentResult, run_agent
from app.services.prompts import PREVISAO_PROMPT_COMPLETO
from app.tools.forecast.tools import build_tools


class ForecastAgent:
    """Projeta consumo, estima a próxima conta, descreve tendência e avalia
    risco de meta. Todo número vem de app.tools.forecast.calculations — o LLM
    não calcula nada (regra anti-alucinação compartilhada)."""

    def __init__(self, user_id: int, llm: Any = None, today: date | None = None) -> None:
        self.user_id = user_id
        self.today = today or date.today()
        if llm is None:
            # Import tardio: mantém o módulo importável sem chaves de API e sem
            # criar clientes reais de LLM (os testes injetam um LLM falso).
            from app.services.llms import llm_especialista

            llm = llm_especialista
        self.llm = llm
        self.tools = build_tools(self.user_id, self.today)

    def run(self, question: str) -> AgentResult:
        """Responde question e devolve texto final + registro de tools."""
        return run_agent(
            llm=self.llm,
            system_prompt=PREVISAO_PROMPT_COMPLETO,
            tools=self.tools,
            question=question,
        )
