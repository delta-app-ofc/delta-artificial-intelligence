"""Agente standalone que responde sobre consumo efetivamente registrado."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from app.agents._runtime import AgentResult, run_agent
from app.services.prompts import consumo_prompt_completo
from app.tools.consumption.analysis import DEFAULT_TIMEZONE
from app.tools.consumption.tools import build_tools


class ConsumptionAgent:
    """Consulta resumos, comparações e picos sem estimar custo ou consumo futuro."""

    def __init__(
        self,
        user_id: int,
        llm: Any = None,
        *,
        now: datetime | None = None,
        clock: Callable[[], datetime] | None = None,
        timezone_name: str = DEFAULT_TIMEZONE,
    ) -> None:
        if now is not None and (now.tzinfo is None or now.utcoffset() is None):
            raise ValueError("now precisa ter fuso horário explícito.")
        if now is not None and clock is not None:
            raise ValueError("Informe now ou clock, não os dois.")

        self.user_id = user_id
        self.timezone_name = timezone_name
        self._clock = clock or (lambda: now or datetime.now(timezone.utc))
        if llm is None:
            # Import tardio para manter testes e imports livres de chamadas externas.
            from app.services.llms import llm_especialista

            llm = llm_especialista
        self.llm = llm
        self.tools = build_tools(
            self.user_id,
            clock=self._clock,
            timezone_name=self.timezone_name,
        )

    def run(self, question: str) -> AgentResult:
        run_now = self._clock()
        run_tools = build_tools(
            self.user_id,
            clock=lambda: run_now,
            timezone_name=self.timezone_name,
        )
        return run_agent(
            llm=self.llm,
            system_prompt=consumo_prompt_completo(
                now=run_now,
                timezone_name=self.timezone_name,
            ),
            tools=run_tools,
            question=question,
        )
