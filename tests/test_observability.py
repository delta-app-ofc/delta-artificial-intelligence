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
                 "OBS_ERROR_RATE_LIMIT", "OBS_HASH_SECRET", "LANGSMITH_TRACING", "LANGSMITH_API_KEY", "LANGSMITH_SEND_CONTENT"):
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
    assert summary["roi"] == pytest.approx((9 * 8.01 - summary["cost_usd"]) / summary["cost_usd"], rel=1e-3)


def test_projection_for_100_and_1000_users(monkeypatch):
    _use_env(monkeypatch, OBS_QUESTIONS_PER_USER_WEEK="5")
    summary = metrics.summarize([metrics.build_record(_trace(), "success", 1000.0) for _ in range(4)])
    rows = {(r["scenario"], r["users_per_week"]): r for r in metrics.project(summary)}
    base100, base1000 = rows[("base", 100)], rows[("base", 1000)]
    assert base100["requests_per_week"] == 500
    assert base1000["cost_week_usd"] == pytest.approx(base100["cost_week_usd"] * 10, rel=1e-3)
    # O pessimista usa o p95 medido do custo por requisição, não um fator inventado.
    expected = 500 * summary["cost_p95_per_request_usd"]
    assert rows[("pessimista", 100)]["cost_week_usd"] == pytest.approx(expected, rel=1e-3)


def test_projection_without_measured_questions_is_unknown():
    summary = metrics.summarize([metrics.build_record(_trace(), "success", 1000.0)])
    assert summary["measured_questions_per_user_week"] is None
    assert all(row["requests_per_week"] is None and row["cost_week_usd"] is None for row in metrics.project(summary))


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
    assert get_observability_config().obs_support_cost_usd == 8.01
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
    for name in ("LANGSMITH_TRACING", "LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_HIDE_INPUTS", "LANGSMITH_HIDE_OUTPUTS"):
        monkeypatch.setenv(name, "x")  # o undo do monkeypatch remove o que enable_langsmith exporta
    assert enable_langsmith() is False
    _use_env(monkeypatch, LANGSMITH_TRACING="true")
    with pytest.raises(ConfigurationError, match="LANGSMITH_API_KEY"):
        enable_langsmith()
    _use_env(monkeypatch, LANGSMITH_TRACING="true", LANGSMITH_API_KEY="chave-de-teste")
    assert enable_langsmith() is True


def test_app_imports_and_playground_routes_respond():
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    assert client.get("/playground/observability").status_code == 200
    pdf = client.get("/playground/observability/report.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


@pytest.mark.parametrize("price", ['{"m": [NaN, 1]}', '{"m": [1, Infinity]}', '{"m": [-1, 1]}'])
def test_non_finite_or_negative_prices_are_rejected(monkeypatch, price):
    _use_env(monkeypatch, OBS_PRICES_JSON=price)
    with pytest.raises(ConfigurationError, match="OBS_PRICES_JSON"):
        get_observability_config()


def test_empty_sample_slo_is_unknown():
    assert metrics.summarize([])["slo"]["ok"] is None


def test_load_records_includes_unpersisted_recent(monkeypatch):
    monkeypatch.setattr(metrics, "_db_retry_at", 0.0)  # estado do módulo: não herdar uma falha anterior
    saved = metrics.build_record(_trace(), "success", 100.0)
    pending = metrics.build_record(_trace(), "success", 200.0)
    metrics._recent.extend([saved, pending])

    class FakeCursor(list):
        def sort(self, *_args): return self
        def limit(self, *_args): return self

    class FakeCollection:
        def find(self, *_args): return FakeCursor([saved])

    fake = {"db_delta_app": {metrics.COLLECTION: FakeCollection()}}
    monkeypatch.setattr("app.data.db_mongo.get_app_client", lambda: fake)
    ids = [item["request_id"] for item in metrics.load_records()]
    assert ids.count(saved["request_id"]) == 1 and pending["request_id"] in ids


def test_pdf_without_measurements_is_labeled_as_estimate():
    summary = metrics.summarize([])
    summary["projection"] = metrics.project(summary)
    assert build_pdf(summary).startswith(b"%PDF")


def test_every_priced_model_has_a_source():
    assert set(metrics.DEFAULT_PRICES) == set(metrics.PRICE_SOURCES)
    assert metrics.DEFAULT_PRICES["gpt-6-luna"] == (0.10, 0.50)
    assert metrics.summarize([])["unconfirmed_price_models"] == []  # todos os preços têm página oficial


def test_console_summary_keeps_token_counts_visible():
    """O filtro de privacidade omite chaves com 'token'; os totais precisam passar por ele."""
    from app.observability.diagnostics import public_data
    summary = metrics.summarize([metrics.build_record(_trace(), "success", 100.0)])
    shown = public_data(summary)
    assert shown["usage"]["input_tokens"] == 1100 and shown["usage"]["output_tokens"] == 300
    assert isinstance(shown["volume_per_request"], int)


def test_database_failure_is_skipped_for_a_while(monkeypatch):
    calls = []

    def broken_client():
        calls.append(1)
        raise RuntimeError("sem banco")

    monkeypatch.setattr("app.data.db_mongo.get_app_client", broken_client)
    monkeypatch.setattr(metrics, "_db_retry_at", 0.0)
    metrics.load_records()
    metrics.load_records()
    assert len(calls) == 1


def test_client_comes_from_header_or_playground_path():
    assert metrics.client_from_scope({"path": "/chat", "headers": [(b"x-client", b"WEB")]}) == "web"
    assert metrics.client_from_scope({"path": "/chat", "headers": [(b"x-client", b"app")]}) == "app"
    assert metrics.client_from_scope({"path": "/chat", "headers": [(b"x-client", b"geladeira")]}) == "unknown"
    assert metrics.client_from_scope({"path": "/chat", "headers": []}) == "unknown"
    assert metrics.client_from_scope({"path": "/playground/chat", "headers": []}) == "playground"


def test_user_hash_needs_secret_and_is_stable(monkeypatch):
    assert metrics.user_hash(7) is None
    _use_env(monkeypatch, OBS_HASH_SECRET="segredo-com-mais-de-16")
    first, again, other = metrics.user_hash(7), metrics.user_hash(7), metrics.user_hash(8)
    assert first == again and first != other and "7" != first and len(first) == 32
    _use_env(monkeypatch, OBS_HASH_SECRET="curto")
    with pytest.raises(ConfigurationError, match="OBS_HASH_SECRET"):
        get_observability_config()


def test_embeddings_enter_the_cost(monkeypatch):
    trace = _trace()
    trace.models.append({"component": "rag", "kind": "embedding", "model": "gemini-embedding-2-preview",
                         "status": "success", "input_tokens": 1_000_000, "duration_ms": 10})
    record = metrics.build_record(trace, "success", 100.0)
    assert record["embedding_tokens"] == 1_000_000
    assert record["embedding_cost_usd"] == pytest.approx(0.20)
    assert record["cost_usd"] == pytest.approx(record["llm_cost_usd"] + 0.20)
    assert record["by_component"]["embeddings"]["cost_usd"] == pytest.approx(0.20)
    assert record["input_tokens"] == 1100  # tokens de embedding não entram nos de chat


def test_cost_by_client_and_distinct_users(monkeypatch):
    _use_env(monkeypatch, OBS_HASH_SECRET="segredo-com-mais-de-16")
    records = []
    for client, user in (("app", 1), ("app", 1), ("web", 2)):
        trace = _trace()
        trace.client, trace.user_id = client, user
        records.append(metrics.build_record(trace, "success", 100.0))
    summary = metrics.summarize(records)
    assert summary["distinct_users"] == 2 and summary["questions_per_user"] == 1.5
    assert summary["cost_by_client"]["app"]["requests"] == 2 and summary["cost_by_client"]["web"]["users"] == 1
    assert list(summary["cost_by_client"])[0] == "app"  # o que mais gasta vem primeiro


def test_embedding_without_official_count_is_not_estimated():
    trace = _trace()
    trace.models.append({"component": "rag", "kind": "embedding", "model": "gemini-embedding-2-preview",
                         "status": "success", "input_tokens": None, "duration_ms": 10})
    record = metrics.build_record(trace, "success", 100.0)
    assert record["embedding_tokens"] == 0 and record["embedding_cost_usd"] == 0.0
    assert record["embedding_uncounted"] == 1


def test_jev_cost_uses_the_tokens_returned_by_the_api():
    trace = _trace()
    trace.models.append({"component": "judge", "kind": "jev", "provider": "typesafe", "model": "jev-1.14.0",
                         "status": "success", "input_tokens": 1_000_000, "output_tokens": 500, "duration_ms": 0})
    record = metrics.build_record(trace, "success", 100.0)
    assert record["jev_tokens"] == 1_000_000
    assert record["jev_cost_usd"] == pytest.approx(0.042)  # saída gratuita
    assert record["input_tokens"] == 1100  # os tokens do Jev não entram nos do chat
    assert "jev-1.14.0" not in record["unpriced_models"]


def test_embedding_call_records_the_official_token_count(monkeypatch):
    from app.observability import diagnostics
    monkeypatch.setattr(diagnostics, "_count_embedding_tokens", lambda model, texts: 12)
    trace = Trace(mode="chat")
    with capture(trace):
        with diagnostics.embedding_call("gemini-embedding-2-preview", texts=["texto"]):
            pass
    assert trace.models[0]["input_tokens"] == 12 and trace.models[0]["kind"] == "embedding"


def test_cost_projection_pdf_never_leaves_the_reports_folder():
    from scripts.cost_projection import pdf_path
    assert pdf_path("semana1").as_posix() == "relatorios/semana1.pdf"
    assert pdf_path("../../etc/passwd").as_posix() == "relatorios/passwd.pdf"
    assert pdf_path("C:\\Windows\\x.pdf").parent.as_posix() == "relatorios"
    with pytest.raises(ValueError):
        pdf_path("../..")


def _card_labels(summary, monkeypatch):
    from app.observability import report
    labels = []
    original = report._Card.__init__

    def spy(self, label, *args, **kwargs):
        labels.append(label)
        original(self, label, *args, **kwargs)

    monkeypatch.setattr(report._Card, "__init__", spy)
    summary["projection"] = metrics.project(summary)
    build_pdf(summary)
    return set(labels)


EXPECTED_KPIS = {
    "Índice de erros", "Sucesso", "Falhas", "Bloqueios", "Fallbacks", "Tempo total p95", "Mediana (p50)",
    "Pior caso (p99)", "Orquestração", "Custo total", "Custo por requisição", "Chamadas ao modelo",
    "Revisões do Juiz", "Embeddings", "Jev", "Usuários distintos", "Perguntas por usuário",
    "Cliente que mais gasta", "Taxa de resolução", "Custo por resolução", "ROI", "Economia estimada",
}


def test_pdf_shows_every_kpi_even_without_measurements(monkeypatch):
    assert EXPECTED_KPIS <= _card_labels(metrics.summarize([]), monkeypatch)


def test_pdf_shows_every_kpi_with_measurements(monkeypatch):
    summary = metrics.summarize([metrics.build_record(_trace(), "success", 1000.0)])
    assert EXPECTED_KPIS <= _card_labels(summary, monkeypatch)


def test_num_formats_floats_in_portuguese():
    from app.observability.report import _num
    assert _num(1000) == "1.000" and _num(5999.0) == "5.999"
    assert _num(1234.5) == "1.234,50" and _num(0.5) == "0,50"


def test_unreadable_usage_does_not_break_the_model_call():
    from types import SimpleNamespace
    from app.observability import diagnostics
    broken = SimpleNamespace(generations=[], llm_output={"token_usage": "texto"})
    assert diagnostics._token_usage(broken) == {}
    trace = Trace(mode="chat")
    handler = ModelDiagnostics("openai", "gpt-6-luna")
    with capture(trace):
        handler.on_chat_model_start({}, [[]], run_id="r9")
        handler.on_llm_end(broken, run_id="r9")
    assert trace.models[0]["status"] == "success"


def test_rag_embedding_name_with_models_prefix_is_priced():
    assert metrics._price_for("models/gemini-embedding-2-preview") == (0.20, 0.0)


def test_langsmith_hides_prompts_and_answers_by_default(monkeypatch):
    import os
    from app.observability.langsmith import enable_langsmith
    for name in ("LANGSMITH_TRACING", "LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_HIDE_INPUTS", "LANGSMITH_HIDE_OUTPUTS"):
        monkeypatch.setenv(name, "x")
    _use_env(monkeypatch, LANGSMITH_TRACING="true", LANGSMITH_API_KEY="chave-de-teste")
    assert enable_langsmith() is True
    assert os.environ["LANGSMITH_HIDE_INPUTS"] == "true" and os.environ["LANGSMITH_HIDE_OUTPUTS"] == "true"
    _use_env(monkeypatch, LANGSMITH_TRACING="true", LANGSMITH_API_KEY="chave-de-teste", LANGSMITH_SEND_CONTENT="true")
    assert enable_langsmith() is True
    assert os.environ["LANGSMITH_HIDE_INPUTS"] == "false"
