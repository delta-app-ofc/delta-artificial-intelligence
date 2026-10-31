"""Testa a política de aprovação do Juiz com uma resposta Jev simulada."""

import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.agents.judge import JudgeAgent, JudgeInput


class FakeClassifier:
    def invoke(self, payload):
        self.payload = payload
        answer = SimpleNamespace(
            choice="no_error",
            confidence=0.95,
            probabilities={"no_error": 0.95},
        )
        noul = lambda: SimpleNamespace(noul=0.9)
        return SimpleNamespace(
            choices={"severity": answer},
            nouls={"facts_supported": noul(), "relevant": noul()},
            usage=SimpleNamespace(model_dump=lambda mode: {"input_tokens": 10}),
            model="jev-test",
            request_id="request-test",
        )


class JudgeAgentSmokeTest(unittest.TestCase):
    def test_run_approves_when_all_criteria_pass(self):
        fake_typesafe = types.ModuleType("langchain_typesafe")

        class Criterion:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        fake_typesafe.Choice = Criterion
        fake_typesafe.Noul = Criterion
        config = SimpleNamespace(
            jev_confidence_threshold=0.7,
            jev_probability_threshold=0.7,
            jev_facts_supported_threshold=0.6,
            jev_relevance_threshold=0.25,
            llm_provider="openai",
            openai_model="model-test",
            judge_specialist_model="specialist-test",
        )
        classifier = FakeClassifier()
        judge_input = JudgeInput(
            question="Qual o consumo?",
            candidate="O consumo foi 700 L.",
            agent_results=[],
        )

        with (
            patch.dict(sys.modules, {"langchain_typesafe": fake_typesafe}),
            patch("app.agents.judge.get_judge_config", return_value=config),
        ):
            result = JudgeAgent(classifier=classifier).run(judge_input)

        self.assertEqual(result.decision, "approve")
        self.assertEqual(result.status, "evaluated")
        self.assertEqual(result.reason_codes, ["ANSWER_APPROVED"])
        self.assertEqual(result.severity, "no_error")
        self.assertEqual(result.assessment["provider"], "typesafe")
        self.assertEqual(classifier.payload["state"]["candidate"], "O consumo foi 700 L.")


if __name__ == "__main__":
    unittest.main()
