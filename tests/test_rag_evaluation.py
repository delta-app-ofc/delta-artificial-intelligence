"""Testa métricas de recuperação com resultados sintéticos."""
from scripts import evaluate_rag


def test_rag_metrics_calculate_hit_and_reciprocal_rank():
    cases = [
        {"id": "a", "question": "a", "expected_heading": "3.3"},
        {"id": "b", "question": "b", "expected_heading": "5.3"},
    ]
    responses = {
        "a": {"status": "ok", "chunks": [{"headings": ["3.3 Histórico"]}]},
        "b": {"status": "ok", "chunks": [{"headings": ["outro"]}, {"headings": ["5.3 Projeção"]}]},
    }
    report = evaluate_rag.evaluate_cases(cases, search=lambda payload: responses[payload["question"]])
    assert report["metrics"]["hit_at_1"] == 0.5
    assert report["metrics"]["hit_at_3"] == 1.0
    assert report["metrics"]["mrr"] == 0.75


def test_rag_unavailable_is_not_scored_as_zero_quality_success():
    report = evaluate_rag.evaluate_cases(
        [{"id": "a", "question": "a", "expected_heading": "3.3"}],
        search=lambda payload: {"status": "unavailable", "chunks": []},
    )
    assert report["metrics"]["unavailable"] == 1
    assert report["metrics"]["hit_at_3"] is None
    assert report["passed"] is False
