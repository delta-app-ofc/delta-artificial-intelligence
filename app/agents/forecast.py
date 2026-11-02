from __future__ import annotations

from datetime import date
from typing import Any

from app.agents._runtime import AgentResult, run_agent
from app.services.prompts import profile_block, full_forecast_prompt
from app.tools.charts import build_forecast_chart
from app.tools.forecast.tools import build_tools


class ForecastAgent:
    def __init__(
        self,
        user_id: int,
        llm: Any = None,
        today: date | None = None,
        access_kind: str | None = None,
    ) -> None:
        """Cria o agente de previsão para `user_id`; `today` fixa a data de referência e
        `access_kind` evita reconsultar o perfil da conta.
        """
        self.user_id = user_id
        self.access_kind = access_kind
        self.today = today or date.today()
        if llm is None:
            from app.services.llms import llm_especialista

            llm = llm_especialista
        self.llm = llm
        self.tools = build_tools(self.user_id, self.today, access_kind)

    def run(
        self,
        question: str,
        *,
        revision_feedback: str | None = None,
        revision_context: dict | None = None,
    ) -> AgentResult:
        result = run_agent(
            llm=self.llm,
            system_prompt=full_forecast_prompt() + profile_block(self.access_kind),
            tools=self.tools,
            question=question,
            revision_feedback=revision_feedback,
            revision_context=revision_context,
        )
        result.chart_data = build_forecast_chart(result.tool_calls)
        return result
