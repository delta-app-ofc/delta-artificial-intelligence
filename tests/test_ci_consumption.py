"""Testa o adaptador de consumo sem acessar banco ou modelo remoto."""

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app.agents.consumption import ConsumptionAgent
from app.agents._runtime import AgentResult


class ConsumptionAgentSmokeTest(unittest.TestCase):
    def test_run_freezes_time_and_forwards_revision(self):
        now = datetime(2026, 4, 7, 12, tzinfo=timezone.utc)
        initial_tools = [object()]
        run_tools = [object()]
        expected = AgentResult(response="Consumo da semana: 700 L.")

        with (
            patch(
                "app.agents.consumption.build_tools",
                side_effect=[initial_tools, run_tools],
            ) as build_tools,
            patch(
                "app.agents.consumption.full_consumption_prompt",
                return_value="prompt de consumo",
            ) as build_prompt,
            patch("app.agents.consumption.run_agent", return_value=expected) as run_agent,
        ):
            agent = ConsumptionAgent(
                42, llm=object(), now=now, timezone_name="America/Sao_Paulo"
            )
            result = agent.run(
                "Quanto consumi?",
                revision_feedback="Use o período semanal.",
                revision_context={"candidate": "resposta anterior"},
            )

        self.assertIs(result, expected)
        self.assertEqual(build_tools.call_count, 2)
        self.assertEqual(build_tools.call_args.args, (42,))
        self.assertEqual(build_tools.call_args.kwargs["clock"](), now)
        build_prompt.assert_called_once_with(
            now=now, timezone_name="America/Sao_Paulo"
        )
        run_agent.assert_called_once_with(
            llm=agent.llm,
            system_prompt="prompt de consumo",
            tools=run_tools,
            question="Quanto consumi?",
            revision_feedback="Use o período semanal.",
            revision_context={"candidate": "resposta anterior"},
        )


if __name__ == "__main__":
    unittest.main()
