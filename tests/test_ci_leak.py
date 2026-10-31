"""Testa a chamada do agente de vazamentos sem serviços externos."""

import unittest
from unittest.mock import patch

from app.agents._runtime import AgentResult, ToolCall
from app.agents.leak import LeakAgent


class LeakAgentSmokeTest(unittest.TestCase):
    def test_run_returns_result_with_leak_chart(self):
        tools = [object()]
        chart = {"type": "leak", "points": []}
        expected = AgentResult(
            response="Há um padrão de consumo contínuo.",
            tool_calls=[ToolCall("analyze_leak", {}, {"status": "ok"})],
        )

        with (
            patch("app.agents.leak.build_tools", return_value=tools),
            patch(
                "app.agents.leak.vazamento_prompt_completo",
                return_value="prompt de vazamento",
            ),
            patch("app.agents.leak.run_agent", return_value=expected) as run_agent,
            patch("app.agents.leak.build_leak_chart", return_value=chart) as build_chart,
        ):
            agent = LeakAgent(42, llm=object())
            result = agent.run(
                "Pode haver vazamento?",
                revision_feedback="Explique a evidência.",
                revision_context={"candidate": "resposta anterior"},
            )

        self.assertIs(result, expected)
        self.assertIs(result.chart_data, chart)
        run_agent.assert_called_once_with(
            llm=agent.llm,
            system_prompt="prompt de vazamento",
            tools=tools,
            question="Pode haver vazamento?",
            revision_feedback="Explique a evidência.",
            revision_context={"candidate": "resposta anterior"},
        )
        build_chart.assert_called_once_with(expected.tool_calls)


if __name__ == "__main__":
    unittest.main()
