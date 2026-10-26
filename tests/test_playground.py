"""Verifica contratos do console; substitutos isolados não comprovam integrações remotas."""
import os
os.environ["APP_ENV"] = "test"

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from app.config import load_settings
from app.main import app
from app.routes import playground as pg
from app.graph import workflow as graph
from app.graph import router as routing
from app.agents._runtime import AgentResult, _run_tool
from app.observability.diagnostics import (
    Trace, ModelDiagnostics, capture, component, current_trace, public_data,
)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(pg, "get_settings", lambda: SimpleNamespace(playground_enabled=True))
    return TestClient(app)


@pytest.fixture
def approved(monkeypatch):
    monkeypatch.setattr(pg, "validate_input",
                        lambda uid, text: {"ok": True, "message": text, "pii_map": {}})
    monkeypatch.setattr(pg, "validate_output",
                        lambda text, **kw: {"ok": True, "response": text})


def test_settings_gate_defaults_and_explicit_override():
    assert load_settings({"APP_ENV": "development"}).playground_enabled
    assert load_settings({"APP_ENV": "test"}).playground_enabled
    assert not load_settings({"APP_ENV": "production"}).playground_enabled
    assert not load_settings({"APP_ENV": "staging"}).playground_enabled
    assert load_settings({"APP_ENV": "production", "DELTA_PLAYGROUND_ENABLED": "true"}).playground_enabled
    assert not load_settings({"APP_ENV": "development", "DELTA_PLAYGROUND_ENABLED": "invalid"}).playground_enabled


@pytest.mark.parametrize("path", ["/playground/", "/playground/config", "/playground/app.js",
                                "/playground/assets/plotly.min.js"])
def test_console_disabled_including_assets(client, monkeypatch, path):
    monkeypatch.setattr(pg, "get_settings", lambda: SimpleNamespace(playground_enabled=False))
    assert client.get(path).status_code == 404


def test_fixed_user_cannot_be_overridden(client):
    response = client.post("/playground/agents/consumption",
                           json={"message": "teste", "user_id": 1})
    assert response.status_code == 422


@pytest.mark.parametrize("payload", [
    {"message": ""}, {"message": "a" * 2001}, {"message": "teste", "session_id": "../other"},
])
def test_invalid_inputs_do_not_execute(client, monkeypatch, payload):
    monkeypatch.setattr(pg, "run_test", lambda *a: pytest.fail("não deve executar"))
    assert client.post("/playground/chat", json=payload).status_code == 422


def test_judge_tab_runs_the_guarded_workflow_and_returns_decisions(client, approved, monkeypatch):
    seen = []
    monkeypatch.setattr(pg, "append_turn", lambda *args: None)
    def workflow(user_id, session_id, message, *, persist_session=True):
        seen.append((user_id, session_id, message, persist_session))
        return {
            "response": "Resposta aprovada.",
            "agent_results": [],
            "judge_history": [{"judge": {
                "decision": "approve", "status": "evaluated", "severity": "no_error",
                "confidence": 0.91, "reason_codes": ["ANSWER_APPROVED"],
                "justification": "A candidata passou pelos critérios.",
                "assessment": {
                    "subcriteria_checked": True, "diagnostics": {"relevant": 0.9},
                    "confidence_threshold": 0.5, "probability_threshold": 0.75,
                    "selected_probability": 0.94,
                    "severity_probabilities": {"no_error": 0.94, "correctable_error": 0.04,
                                               "critical_error": 0.02},
                    "input_summary": {"tools": [
                        {"name": "calculate_forecast", "output_type": "dict"}
                    ]},
                },
            }}],
        }
    monkeypatch.setattr(pg, "run_workflow", workflow)
    response = client.post("/playground/agents/judge", json={"message": "teste"}).json()
    assert seen == [(12345679, response["session_id"], "teste", False)]
    assert response["response"] == "Resposta aprovada."
    assert response["judge_results"][0]["decision"] == "approve"
    assert response["judge_results"][0]["assessment"]["diagnostics"] == {"relevant": 0.9}
    assessment = response["judge_results"][0]["assessment"]
    assert assessment["confidence_threshold"] == 0.5
    assert assessment["probability_threshold"] == 0.75
    assert assessment["selected_probability"] == 0.94
    assert assessment["severity_probabilities"]["no_error"] == 0.94
    assert assessment["input_summary"]["tools"] == [
        {"name": "calculate_forecast", "output_type": "dict"}
    ]


def test_individual_agent_uses_real_contract_and_fixed_identity(client, approved, monkeypatch):
    seen = []
    class Agent:
        def run(self, question):
            seen.append(question)
            return AgentResult(response="Consumo registrado.")
    def load(name, uid):
        seen.append((name, uid))
        return Agent()
    monkeypatch.setattr(graph, "load_agent", load)
    response = client.post("/playground/agents/consumption",
                           json={"message": "Quanto consumi?"}).json()
    assert seen == [("consumption", 12345679), "Quanto consumi?"]
    assert response["status"] == "success"
    assert response["diagnostics"]["executed_agents"] == ["consumption"]
    assert response["response"] == "Consumo registrado."


def test_unimplemented_is_different_from_broken(client, approved, monkeypatch):
    def pending(*args):
        raise routing.AgentNotImplemented()
    monkeypatch.setattr(graph, "load_agent", pending)
    result = client.post("/playground/agents/consumption", json={"message": "teste"}).json()
    assert result["status"] == "skipped"
    assert result["diagnostics"]["errors"] == []
    def broken(*args):
        raise RuntimeError("secret=do-not-expose postgres://name:password@host/db")
    monkeypatch.setattr(graph, "load_agent", broken)
    result = client.post("/playground/agents/consumption", json={"message": "teste"}).json()
    assert result["status"] == "error"
    assert "do-not-expose" not in str(result)
    assert "password@host" not in str(result)
    assert result["diagnostics"]["errors"][0]["code"] == "RuntimeError"


def test_one_failed_agent_preserves_other_answers(monkeypatch):
    class Agent:
        def run(self, question):
            return AgentResult(response="Resposta válida.")
    def load(name, uid):
        if name == "leak":
            raise RuntimeError("falha")
        return Agent()
    monkeypatch.setattr(graph, "load_agent", load)
    state = {"selected_agents": ["leak", "consumption"], "user_id": 12345679, "question": "teste"}
    with capture(Trace("chat")) as trace:
        state = graph._execute_node(state)
        state = graph._respond_node(state)
    assert state["response"] == "Resposta válida."
    assert [r["status"] for r in state["agent_results"]] == ["error", "success"]
    assert trace.executed_agents == ["consumption"]


def test_router_deduplicates_and_records_unknown_agents(monkeypatch):
    import app.services.llms as llms
    fake = SimpleNamespace(invoke=lambda *a: SimpleNamespace(
        content='{"intent":"mixed","complexity":"medium","agents":["consumption","judge","consumption"]}'))
    monkeypatch.setattr(llms, "llm_rapido", fake, raising=False)
    with capture(Trace("router")) as trace:
        decision = routing.classify("teste", {})
    assert decision.agents == ["consumption"]
    assert trace.skipped_agents == ["judge"]
    assert "consumption" in routing.AGENT_REGISTRY


def test_router_failure_is_visible(monkeypatch):
    import app.services.llms as llms
    monkeypatch.setattr(llms, "llm_rapido", None, raising=False)
    with capture(Trace("router")) as trace:
        result = routing.classify("teste", {})
    assert result.agents == []
    assert trace.errors[0]["stage"] == "router"


@pytest.mark.parametrize("intent, prefix", [("greeting", "Oi!"), ("unknown", "Não entendi")])
def test_greeting_workflow_keeps_guards_without_specialists_or_judge(monkeypatch, intent, prefix):
    checked = []
    monkeypatch.setattr(graph, "_history_from_mongo", lambda *args: [])
    monkeypatch.setattr(graph, "build_context", lambda *args: {})
    monkeypatch.setattr(graph, "validate_input", lambda uid, text: {
        "ok": True, "message": text, "pii_map": {},
    })
    monkeypatch.setattr(graph, "classify", lambda *args: routing.RoutingDecision(
        intent=intent, complexity="simple", agents=[],
    ))
    monkeypatch.setattr(graph, "load_agent", lambda *args: pytest.fail("Sem especialista para saudação."))
    monkeypatch.setattr(graph, "JudgeAgent", lambda: pytest.fail("Sem candidata factual para julgar."))
    def output_guard(text, pii_map):
        checked.append(text)
        return {"ok": True, "response": text}
    monkeypatch.setattr(graph, "validate_output", output_guard)
    state = graph.run_workflow(12345679, f"greeting-{intent}", "oi", persist_session=False)
    assert state["response"].startswith(prefix)
    assert checked == [state["response"]]
    assert state["selected_agents"] == []
    assert state["judge_history"] == []


def test_greeting_with_request_keeps_specialist_answer():
    state = {
        "question": "Oi, quanto consumi esta semana?", "intent": "consumption_history",
        "selected_agents": ["consumption"],
        "agent_results": [{"agent": "consumption", "status": "success", "answer": "Foram 1200 litros."}],
    }
    response = graph._respond_node(state)
    assert response["response"] == "Foram 1200 litros."
    assert graph._compose_node(state | response)["composition_status"] == "ready"


def test_router_tab_classifies_without_running_specialists(client, approved, monkeypatch):
    monkeypatch.setattr(pg, "classify", lambda *a: routing.RoutingDecision(
        intent="consumption", complexity="simple", agents=["consumption"]))
    import app.graph.context as context
    monkeypatch.setattr(context, "build_context", lambda *a: {})
    monkeypatch.setattr(pg, "execute_agent", lambda *a: pytest.fail("somente classificar"))
    result = client.post("/playground/router", json={"message": "Quanto consumi?"}).json()
    assert result["diagnostics"]["selected_agents"] == ["consumption"]
    assert result["diagnostics"]["executed_agents"] == []


def test_guardrail_rejection_prevents_agent(client, monkeypatch):
    monkeypatch.setattr(pg, "validate_input", lambda *a: {"ok": False, "reason": "Mensagem bloqueada."})
    monkeypatch.setattr(pg, "execute_agent", lambda *a: pytest.fail("mensagem bloqueada"))
    result = client.post("/playground/agents/consumption", json={"message": "teste"}).json()
    assert result["status"] == "error"
    assert result["diagnostics"]["errors"][0]["code"] == "input_rejected"


def test_chat_preserves_response_when_session_save_fails(client, approved, monkeypatch):
    def workflow(*args, **kwargs):
        trace = current_trace()
        trace.executed_agents.append("consumption")
        trace.selected_agents.append("consumption")
        return {"response": "Resposta do fluxo.", "agent_results": [
            {"agent": "consumption", "status": "success", "answer": "Resposta do fluxo."}]}
    monkeypatch.setattr(pg, "run_workflow", workflow)
    def save(*args):
        raise RuntimeError("secret=private")
    monkeypatch.setattr(pg, "append_turn", save)
    result = client.post("/playground/chat", json={"message": "teste"}).json()
    assert result["status"] == "partial"
    assert result["response"] == "Resposta do fluxo."
    assert "judge" not in result["diagnostics"]["skipped_agents"]
    assert any(e["stage"] == "session_save" for e in result["diagnostics"]["errors"])
    assert "private" not in str(result)


def test_tools_record_failures_and_do_not_turn_them_into_zero():
    with capture(Trace("consumption")) as trace:
        result = _run_tool(None, "missing_tool", {})
    assert result["status"] == "error"
    assert trace.tools[0]["name"] == "missing_tool"
    assert trace.errors[0]["code"] == "tool_error"


def test_actual_langchain_callbacks_record_success_and_fallback():
    from app.services.llms import _FallbackLLM
    class BrokenModel(BaseChatModel):
        @property
        def _llm_type(self):
            return "broken-test"
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            raise httpx.ConnectError("connection failed")
    primary = BrokenModel(callbacks=[ModelDiagnostics("google", "primary-test")])
    secondary = GenericFakeChatModel(
        messages=iter([AIMessage(content="resposta")]),
        callbacks=[ModelDiagnostics("groq", "fallback-test")])
    with capture(Trace("consumption")) as trace:
        with component("consumption"):
            response = _FallbackLLM(primary, secondary).invoke("teste")
    assert response.content == "resposta"
    assert [(m["model"], m["status"], m["fallback"]) for m in trace.models] == [
        ("primary-test", "error", False), ("fallback-test", "success", True)]
    assert all(m["component"] == "consumption" for m in trace.models)


def test_request_traces_are_isolated_across_threads():
    def worker(label):
        with capture(Trace(label)):
            return current_trace().mode
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(worker, ["first", "second"])) == ["first", "second"]
    assert current_trace() is None


def test_sensitive_diagnostic_fields_are_redacted():
    result = public_data({"api_key": "private", "nested": {"password": "private"},
                          "message": "mongodb+srv://user:private@host/db"})
    assert "private" not in str(result)


def test_static_files_and_plotly_local_asset(client):
    assert client.get("/playground/").status_code == 200
    assert client.get("/playground/app.js").status_code == 200
    assert client.get("/playground/assets/plotly.min.js").status_code == 200
    assert client.get("/playground/%2e%2e%2fapp/config.py").status_code == 404


def test_unknown_agent_is_404(client):
    assert client.post("/playground/agents/finance", json={"message": "teste"}).status_code == 404
def test_real_graph_preserves_trace_across_nodes(client, approved, monkeypatch):
    import app.services.llms as llms
    routing_model = GenericFakeChatModel(
        messages=iter([AIMessage(content='{"intent":"consumption","complexity":"simple","agents":["consumption"]}')]),
        callbacks=[ModelDiagnostics("groq", "router-test")])
    monkeypatch.setattr(llms, "llm_rapido", routing_model, raising=False)
    monkeypatch.setattr(graph, "build_context",
                        lambda *a: {"recent_messages": [], "relevant_memory": []})
    class Agent:
        def run(self, question):
            _run_tool(SimpleNamespace(invoke=lambda args: {"status": "ok", "liters": 10}),
                      "daily_total", {})
            return AgentResult(response="Total retornado pela ferramenta.")
    monkeypatch.setattr(graph, "load_agent", lambda name, uid: Agent())
    saved = []
    monkeypatch.setattr(pg, "append_turn", lambda *a: saved.append(a))
    result = client.post("/playground/chat", json={"message": "Quanto consumi?"}).json()
    assert result["status"] == "success"
    assert result["diagnostics"]["selected_agents"] == ["consumption"]
    assert result["diagnostics"]["executed_agents"] == ["consumption"]
    assert result["diagnostics"]["models"][0]["component"] == "router"
    assert result["diagnostics"]["tools"][0]["agent"] == "consumption"
    assert len(saved) == 2 and all(turn[1] == 12345679 for turn in saved)


def test_context_degradation_is_visible_without_failing_other_stages(monkeypatch):
    import app.graph.context as context
    import app.memory.session as session
    def fail(*args):
        raise RuntimeError("sensitive connection details")
    monkeypatch.setattr(session, "load_history_validated", fail)
    with capture(Trace("chat")) as trace:
        with component("context"):
            result = context.build_context(12345679, "session", "teste")
    assert result["recent_messages"] == []
    assert trace.errors[0]["stage"] == "session_history"
    assert trace.stages[-1]["status"] == "partial"
    assert "sensitive" not in str(trace.snapshot())
def test_memory_search_never_creates_or_recreates_collection(monkeypatch):
    import app.memory.long_term as memory
    monkeypatch.setattr(memory, "_ensure_collection",
                        lambda: pytest.fail("consulta não pode alterar schema"))
    monkeypatch.setattr(memory, "_embed_model",
                        lambda: SimpleNamespace(embed_query=lambda text: [0.1]))
    monkeypatch.setattr(memory, "_qdrant", lambda: SimpleNamespace(
        query_points=lambda **kwargs: SimpleNamespace(points=[])))
    with capture(Trace("chat")) as trace:
        assert memory.search_memory(12345679, "antes") == []
    assert trace.errors == []
    assert trace.models[0]["kind"] == "embedding"
