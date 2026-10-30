"""Testa o agente de hábitos sem consultar o banco de dados."""

import unittest
from unittest.mock import patch

from app.agents._runtime import AgentResult, ToolCall
from app.agents.habits import HabitsAgent


class HabitsAgentSmokeTest(unittest.TestCase):
    def test_run_returns_result_with_habits_chart(self):
        tools = [object()]
        chart = {"type": "habits", "points": []}
        expected = AgentResult(
            response="Seu maior consumo ocorre pela manhã.",
            tool_calls=[ToolCall("analyze_habits", {}, {"status": "ok"})],
        )

        with (
            patch("app.agents.habits.build_tools", return_value=tools) as build_tools,
            patch(
                "app.agents.habits.habitos_prompt_completo",
                return_value="prompt de hábitos",
            ),
            patch("app.agents.habits.run_agent", return_value=expected) as run_agent,
            patch("app.agents.habits.build_habits_chart", return_value=chart) as build_chart,
        ):
            agent = HabitsAgent(42, llm=object())
            result = agent.run("Quais são meus hábitos de consumo?")

        self.assertIs(result, expected)
        self.assertIs(result.chart_data, chart)
        build_tools.assert_called_once_with(42)
        run_agent.assert_called_once_with(
            llm=agent.llm,
            system_prompt="prompt de hábitos",
            tools=tools,
            question="Quais são meus hábitos de consumo?",
            revision_feedback=None,
            revision_context=None,
        )
        build_chart.assert_called_once_with(expected.tool_calls)


if __name__ == "__main__":
    unittest.main()
