"""Testa as métricas do avaliador de roteamento sem chamar um provedor."""
from types import SimpleNamespace

from app.observability.diagnostics import Trace, capture
from scripts import evaluate_router


def test_router_metrics_calculate_set_precision_recall_and_exact_accuracy(monkeypatch):
    decisions = {
        "a": SimpleNamespace(agents=["consumption"], intent="consumption", complexity="simple"),
        "b": SimpleNamespace(agents=["forecast", "consumption"], intent="forecast", complexity="complex"),
    }

    def fake_classify(question, context):
        return decisions[question]

    monkeypatch.setattr(evaluate_router, "classify", fake_classify)
    report = evaluate_router.evaluate_cases([
        {"id": "a", "question": "a", "access_kind": "residential", "intent": "consumption", "agents": ["consumption"], "complexity": "simple"},
        {"id": "b", "question": "b", "access_kind": "residential", "intent": "consumption", "agents": ["consumption"], "complexity": "simple"},
    ])
    assert report["metrics"]["exact_route_accuracy"] == 0.5
    assert report["metrics"]["agent_precision"] == 2 / 3
    assert report["metrics"]["agent_recall"] == 1.0
    assert report["metrics"]["unavailable"] == 0


def test_router_evaluation_marks_provider_error_unavailable(monkeypatch):
    from app.observability import diagnostics

    def failing_classify(question, context):
        diagnostics.current_trace().error("router", TimeoutError("teste"))
        return SimpleNamespace(agents=[], intent="routing_unavailable", complexity="simple")

    monkeypatch.setattr(evaluate_router, "classify", failing_classify)
    report = evaluate_router.evaluate_cases([
        {"id": "a", "question": "a", "access_kind": "residential", "intent": "consumption", "agents": ["consumption"], "complexity": "simple"},
    ])
    assert report["metrics"]["unavailable"] == 1
    assert report["passed"] is False
