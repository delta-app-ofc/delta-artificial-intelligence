"""Testa a decisão do juiz especialista com um modelo estruturado simulado."""

import unittest
from types import SimpleNamespace

from app.agents.judge import JudgeInput, JudgeResult
from app.agents.judge_specialist import SpecialistJudgeAgent, SpecialistVerdict
from unittest.mock import patch


class FakeStructuredModel:
    def __init__(self):
        self.messages = None

    def with_structured_output(self, schema, *, method):
        if schema is not SpecialistVerdict or method != "json_schema":
            raise AssertionError("O juiz deve solicitar a saída estruturada esperada.")
        return self

    def invoke(self, messages):
        self.messages = messages
        return {
            "decision": "approve",
            "severity": "no_error",
            "justification": "A candidata está apoiada nas evidências disponíveis.",
        }


class SpecialistJudgeAgentSmokeTest(unittest.TestCase):
    def test_run_approves_consistent_structured_verdict(self):
        model = FakeStructuredModel()
        config = SimpleNamespace(
            llm_provider="openai",
            openai_model="model-test",
            judge_specialist_model="specialist-test",
        )
        jev_result = JudgeResult(
            decision="correct",
            status="evaluated",
            justification="Confiança abaixo do limite.",
            reason_codes=["LOW_CONFIDENCE"],
            confidence=0.5,
            severity="no_error",
        )
        judge_input = JudgeInput(
            question="Qual o consumo?",
            candidate="O consumo foi 700 L.",
            agent_results=[],
        )

        with patch("app.agents.judge_specialist.get_judge_config", return_value=config):
            result = SpecialistJudgeAgent(llm=model).run(
                judge_input, jev_result=jev_result
            )

        self.assertEqual(result.decision, "approve")
        self.assertEqual(result.status, "evaluated")
        self.assertEqual(result.reason_codes, ["SPECIALIST_APPROVE"])
        self.assertEqual(result.assessment["reviewer"], "specialist")
        self.assertIn("O consumo foi 700 L.", model.messages[1][1])


if __name__ == "__main__":
    unittest.main()
