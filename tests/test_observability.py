"""Métricas de observabilidade: custo, latência, resolução, ROI, projeção e PDF."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config import ConfigurationError, get_observability_config, get_settings
from app.observability import metrics
from app.observability.diagnostics import ModelDiagnostics, Trace, capture, component
from app.observability.report import build_pdf


def _use_env(monkeypatch, **values):
    """Recarrega os settings com as variáveis dadas (APP_ENV=test ignora o .env)."""
    monkeypatch.setenv("APP_ENV", "test")
    for name in ("OBS_PRICES_JSON", "OBS_SUPPORT_COST_USD", "OBS_QUESTIONS_PER_USER_WEEK", "OBS_USD_TO_BRL",
                 "OBS_JEV_COST_USD", "OBS_ERROR_RATE_LIMIT", "LANGSMITH_TRACING", "LANGSMITH_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    get_settings(refresh=True)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    _use_env(monkeypatch)
    metrics.clear_memory()
    yield
    monkeypatch.undo()
    get_settings(refresh=True)


def _trace(blocked: bool = False) -> Trace:
    trace = Trace(mode="chat", user_id=1)
    trace.models.append({"component": "consumption", "model": "gemini-2.5-flash", "status": "success",
                         "input_tokens": 1000, "output_tokens": 200, "duration_ms": 500, "fallback": False})
    trace.models.append({"component": "consumption", "model": "openai/gpt-oss-120b", "status": "success",
                         "input_tokens": 100, "output_tokens": 100, "duration_ms": 50, "fallback": True})
    with capture(trace):
        with component("consumption"):
            pass
    trace.event("graph.node.end", component="execute", duration_ms=600)
    trace.event("graph.node.end", component="judge", duration_ms=300)
    if blocked:
        trace.event("graph.node.end", component="block", duration_ms=1)
    return trace


def test_model_cost_uses_price_table():
    assert metrics.model_cost("gemini-2.5-flash", 1_000_000, 1_000_000) == pytest.approx(2.80)
    assert metrics.model_cost("modelo-desconhecido", 10, 10) == 0.0


def test_prices_can_be_overridden(monkeypatch):
    _use_env(monkeypatch, OBS_PRICES_JSON='{"gpt-6-luna": [2, 4]}')
    assert metrics.model_cost("gpt-6-luna", 1_000_000, 1_000_000) == pytest.approx(6.0)


def test_build_record_sums_tokens_cost_and_latency():
    record = metrics.build_record(_trace(), "success", 1000.0)
    assert record["input_tokens"] == 1100 and record["output_tokens"] == 300
    assert record["cost_usd"] == pytest.approx(0.0003 + 0.0005 + 0.000015 + 0.00006, rel=1e-3)
    assert record["nodes_ms"]["execute"] == 600
    assert record["overhead_ms"] == 100.0
    assert record["fallback_calls"] == 1
    assert record["resolved"] is True


def test_blocked_by_judge_is_not_resolution():
    assert metrics.build_record(_trace(blocked=True), "success", 1000.0)["resolved"] is False
    assert metrics.build_record(_trace(), "error", 1000.0)["resolved"] is False


def test_record_has_no_prompt_or_personal_text():
    record = metrics.build_record(_trace(), "success", 10.0)
    assert not {"question", "response", "message", "user_id"} & set(record)


def test_percentile_nearest_rank():
    assert metrics.percentile([10, 20, 30, 40], 95) == 40
    assert metrics.percentile([], 95) == 0.0


def test_summary_error_rate_cost_per_resolution_and_roi():
    records = [metrics.build_record(_trace(), "success", 1000.0) for _ in range(9)]
    records.append(metrics.build_record(_trace(), "error", 9000.0))
    summary = metrics.summarize(records)
    assert summary["error_rate"] == 0.1
    assert summary["slo"]["ok"] is False
    assert summary["resolutions"] == 9
    assert summary["cost_per_resolution_usd"] == pytest.approx(summary["cost_usd"] / 9, rel=1e-3)
    assert summary["roi"] == pytest.approx((9 * 2.0 - summary["cost_usd"]) / summary["cost_usd"], rel=1e-3)


def test_projection_for_100_and_1000_users():
    summary = metrics.summarize([metrics.build_record(_trace(), "success", 1000.0) for _ in range(4)])
    rows = {(r["scenario"], r["users_per_week"]): r for r in metrics.project(summary)}
    base100, base1000 = rows[("base", 100)], rows[("base", 1000)]
    assert base100["requests_per_week"] == 500
    assert base1000["cost_week_usd"] == pytest.approx(base100["cost_week_usd"] * 10, rel=1e-3)
    assert rows[("pessimista", 100)]["cost_week_usd"] == pytest.approx(base100["cost_week_usd"] * 1.5, rel=1e-3)


def test_empty_summary_does_not_divide_by_zero():
    summary = metrics.summarize([])
    assert summary["cost_per_resolution_usd"] is None and summary["roi"] is None
    assert all(row["cost_per_resolution_usd"] is None for row in metrics.project(summary))


def test_model_callback_reads_usage_metadata():
    message = SimpleNamespace(usage_metadata={"input_tokens": 12, "output_tokens": 7,
                                              "output_token_details": {"reasoning": 3}})
    response = SimpleNamespace(generations=[[SimpleNamespace(message=message)]], llm_output=None)
    trace = Trace(mode="chat")
    handler = ModelDiagnostics("openai", "gpt-6-luna")
    with capture(trace):
        handler.on_chat_model_start({}, [[]], run_id="r1")
        handler.on_llm_end(response, run_id="r1")
    row = trace.models[0]
    assert (row["input_tokens"], row["output_tokens"], row["reasoning_tokens"]) == (12, 7, 3)


def test_record_request_ignores_unrecorded_modes():
    metrics.record_request(Trace(mode="http"), "success", 5.0)
    assert not list(metrics._recent)


def test_pdf_is_generated():
    summary = metrics.summarize([metrics.build_record(_trace(), "success", 1000.0)])
    summary["projection"] = metrics.project(summary)
    pdf = build_pdf(summary)
    assert pdf.startswith(b"%PDF") and len(pdf) > 1000


def test_settings_use_defaults_and_overrides(monkeypatch):
    assert get_observability_config().obs_support_cost_usd == 2.0
    _use_env(monkeypatch, OBS_SUPPORT_COST_USD="3.5", OBS_QUESTIONS_PER_USER_WEEK="10")
    assert metrics.assumptions()["support_cost_per_resolution_usd"] == 3.5
    assert metrics.assumptions()["questions_per_user_per_week"] == 10.0


@pytest.mark.parametrize("name,value", [
    ("OBS_SUPPORT_COST_USD", "-1"), ("OBS_USD_TO_BRL", "abc"), ("OBS_ERROR_RATE_LIMIT", "2"),
    ("OBS_PRICES_JSON", "not-json"), ("LANGSMITH_TRACING", "talvez"),
])
def test_invalid_settings_raise_clear_error(monkeypatch, name, value):
    _use_env(monkeypatch, **{name: value})
    with pytest.raises(ConfigurationError, match=name):
        get_observability_config()


def test_langsmith_needs_key_and_stays_off_by_default(monkeypatch):
    from app.observability.langsmith import enable_langsmith
    for name in ("LANGSMITH_TRACING", "LANGSMITH_API_KEY", "LANGSMITH_PROJECT"):
        monkeypatch.setenv(name, "x")  # o undo do monkeypatch remove o que enable_langsmith exporta
    assert enable_langsmith() is False
    _use_env(monkeypatch, LANGSMITH_TRACING="true")
    with pytest.raises(ConfigurationError, match="LANGSMITH_API_KEY"):
        enable_langsmith()
    _use_env(monkeypatch, LANGSMITH_TRACING="true", LANGSMITH_API_KEY="chave-de-teste")
    assert enable_langsmith() is True
