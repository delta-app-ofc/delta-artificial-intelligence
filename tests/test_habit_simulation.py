"""Testa a simulação de hábitos hipotéticos sem consultar banco nem LLM reais."""

import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.graph import synthesis
from app.services.prompts import ROUTER_PROMPT, SYNTHESIS_PROMPT, full_habits_prompt
from app.tools.exceptions import RegionRateNotFound
from app.tools.habits import tools as habit_tools
from app.tools.habits.tools import parse_frequency


def _cost_tool():
    tools = {t.name: t for t in habit_tools.build_tools(7, "residential")}
    return tools


class ParseFrequencyTest(unittest.TestCase):
    def test_natural_phrases(self):
        cases = {
            "3 vzs por semana": 3,
            "3x na semana": 3,
            "3 vezes": 3,
            "três vezes por semana": 3,
            "duas vezes": 2,
            "uma vez por semana": 1,
            "todo dia": 7,
            "todos os dias": 7,
            "toda semana": 1,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_frequency(text), expected)

    def test_returns_none_when_unclear(self):
        for text in ["2 vezes por mês", "a cada quinze dias", "sempre", "8x", "0 vezes"]:
            with self.subTest(text=text):
                self.assertIsNone(parse_frequency(text))


class HypotheticalSimulationTest(unittest.TestCase):
    def _invoke(self, args, rate=Decimal("10")):
        pg = habit_tools.db_postgres
        with (
            patch.object(pg, "get_user_region_id", return_value=1),
            patch.object(pg, "get_user_property_classification_id", return_value=2),
            patch.object(pg, "get_current_region_rate", return_value=rate) as get_rate,
            patch.object(pg, "get_user_habits", side_effect=AssertionError("não deve ler o cadastro")),
            patch.object(pg, "create_habit", side_effect=AssertionError("simular não grava")),
        ):
            tools = _cost_tool()
            return tools["estimate_habit_water_cost"].invoke(args), get_rate

    def test_hypothetical_habit_with_free_text_frequency_and_rate(self):
        out, _ = self._invoke({"habit_name": "lavar roupa", "frequency_text": "3 vzs por semana"})
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["liters_per_week"], 300.0)
        self.assertEqual(out["liters_per_month"], 1299.0)
        self.assertEqual(out["cost_per_month"], 12.99)

    def test_without_rate_returns_liters_and_no_price(self):
        pg = habit_tools.db_postgres
        with (
            patch.object(pg, "get_user_region_id", return_value=1),
            patch.object(pg, "get_user_property_classification_id", return_value=2),
            patch.object(pg, "get_current_region_rate", side_effect=RegionRateNotFound("x")),
        ):
            out = _cost_tool()["estimate_habit_water_cost"].invoke(
                {"habit_name": "lavar roupa", "frequency": 3}
            )
        self.assertEqual(out["status"], "rate_unavailable")
        self.assertEqual(out["liters_per_month"], 1299.0)
        self.assertNotIn("cost_per_month", out)

    def test_missing_frequency_asks_only_for_it(self):
        out, get_rate = self._invoke({"habit_name": "lavar roupa"})
        self.assertEqual(out["status"], "needs_frequency")
        get_rate.assert_not_called()

    def test_unparseable_frequency_text_asks_for_frequency(self):
        out, _ = self._invoke({"habit_name": "lavar roupa", "frequency_text": "2 vezes por mês"})
        self.assertEqual(out["status"], "needs_frequency")

    def test_simulation_tool_does_not_expose_user_id(self):
        self.assertNotIn("user_id", _cost_tool()["estimate_habit_water_cost"].args)


class PromptContractTest(unittest.TestCase):
    def test_habits_prompt_allows_simulation_without_registration(self):
        prompt = full_habits_prompt()
        self.assertIn("estimate_habit_water_cost", prompt)
        self.assertIn("Simulação não é cadastro", prompt)
        self.assertIn("simular NUNCA chama `create_habit`", prompt)
        self.assertIn("não acrescente energia, detergente", prompt)
        self.assertIn('Não pergunte\n  "quer que eu estime?"', prompt)

    def test_router_sends_simulation_to_habits(self):
        self.assertIn("habit_cost_simulation", ROUTER_PROMPT)

    def test_synthesis_prompt_does_not_ask_for_agent_attribution(self):
        self.assertNotIn("qual agente", SYNTHESIS_PROMPT)
        self.assertIn("Nunca cite nomes internos", SYNTHESIS_PROMPT)


class SynthesisLabelsTest(unittest.TestCase):
    def test_internal_agent_names_are_not_sent_to_the_model(self):
        fake_llm = MagicMock()
        fake_llm.invoke.return_value = MagicMock(content="Resposta unificada.")
        answers = [
            {"agent": "habits", "answer": "Lavar roupa gasta 300 L por semana."},
            {"agent": "forecast", "answer": "A conta deve ficar em R$ 80."},
        ]
        with patch("app.services.llms.llm_rapido", fake_llm):
            out = synthesis.synthesize("Quanto vou gastar?", answers)

        self.assertEqual(out["response"], "Resposta unificada.")
        system_prompt = fake_llm.invoke.call_args.args[0][0].content
        for internal in ("HABITS", "FORECAST", "habits", "forecast"):
            self.assertNotIn(internal, system_prompt)
        self.assertIn("[Informação 1]", system_prompt)
        self.assertIn("[Informação 2]", system_prompt)


if __name__ == "__main__":
    unittest.main()
