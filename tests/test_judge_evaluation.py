"""Testa o avaliador do Juiz com um classificador Jev controlado."""
from types import SimpleNamespace

from app.agents.judge import JudgeAgent
from scripts import evaluate_judge


class FakeClassifier:
    def invoke(self, payload):
        candidate = payload["state"]["candidate"]
        bad = "950" in candidate or "120,00" in candidate or "confirmado" in candidate
        severity = "correctable_error" if bad else "no_error"
        answer = SimpleNamespace(choice=severity, confidence=0.95, probabilities={severity: 0.95})
        noul = lambda: SimpleNamespace(noul=0.95 if not bad else 0.20)
        return SimpleNamespace(
            choices={"severity": answer},
            nouls={"facts_supported": noul(), "relevant": SimpleNamespace(noul=0.95)},
            usage=SimpleNamespace(model_dump=lambda mode: {"input_tokens": 10}),
            model="jev-test", request_id="request-test",
        )


def test_judge_evaluation_reports_all_controlled_cases_as_passed():
    cases = [
        {"id": "ok", "question": "q", "candidate": "700 litros", "agent_results": [], "expected_decision": "approve", "expected_severity": "no_error"},
        {"id": "bad", "question": "q", "candidate": "950 litros", "agent_results": [], "expected_decision": "correct", "expected_severity": "correctable_error"},
    ]
    report = evaluate_judge.evaluate_cases(cases, classifier=FakeClassifier())
    assert report["passed"] is True
    assert report["metrics"]["decision_accuracy"] == 1.0


def test_judge_evaluation_counts_unavailable_provider(monkeypatch):
    monkeypatch.setattr(JudgeAgent, "run", lambda self, value: SimpleNamespace(
        status="unavailable", decision="reject", severity=None, reason_codes=["test"],
    ))
    report = evaluate_judge.evaluate_cases([{
        "id": "x", "question": "q", "candidate": "x", "agent_results": [],
        "expected_decision": "approve", "expected_severity": "no_error",
    }])
    assert report["metrics"]["unavailable"] == 1
    assert report["passed"] is False
