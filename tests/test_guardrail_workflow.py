"""Testes de integração do workflow LangGraph com guardrails, context-passing e síntese."""

from __future__ import annotations

import pytest

from app.graph.workflow import run_workflow


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _ok_guard(message="Quanto consumi?", pii_map=None):
    return {"ok": True, "message": message, "pii_map": pii_map or {}}


def _blocked_guard(reason="Mensagem bloqueada."):
    return {"ok": False, "reason": reason}


def _fake_agent(name: str, answer: str):
    class _FakeAgent:
        def run(self, question):
            class _R:
                response = answer
                chart_data = None
                tool_calls = []
            return _R()
    return _FakeAgent()


# ---------------------------------------------------------------------------
# guardrail de entrada no workflow
# ---------------------------------------------------------------------------

def test_blocked_input_skips_all_agents(monkeypatch):
    monkeypatch.setattr("app.guardrails.input.validate_input", lambda uid, msg: _blocked_guard())
    monkeypatch.setattr("app.guardrails.output.validate_output", lambda r, **kw: {"ok": True, "response": r})
    monkeypatch.setattr("app.memory.session.append_turn", lambda *a, **kw: None)

    state = run_workflow(1, "sess-1", "mensagem ruim")

    assert "agente" in state.get("response", "").lower() or state.get("_blocked") is True
    assert state.get("agent_results", []) == []


def test_pii_map_stored_in_state(monkeypatch):
    pii_map = {"[PII_CPF_abc]": "111.222.333-44"}
    monkeypatch.setattr("app.guardrails.input.validate_input", lambda uid, msg: _ok_guard(pii_map=pii_map))
    monkeypatch.setattr("app.graph.workflow.build_context", lambda *a, **kw: {"recent_messages": [], "relevant_memory": []})
    from app.graph.router import RoutingDecision
    monkeypatch.setattr("app.graph.workflow.classify", lambda q, ctx: RoutingDecision(intent="unknown", complexity="simple", agents=[]))
    monkeypatch.setattr("app.guardrails.output.validate_output", lambda r, pii_map=None: {"ok": True, "response": r})
    monkeypatch.setattr("app.memory.session.append_turn", lambda *a, **kw: None)

    state = run_workflow(1, "sess-2", "CPF: 111.222.333-44")

    assert state.get("pii_map") == pii_map


def test_valid_input_reaches_router(monkeypatch):
    called = []
    monkeypatch.setattr("app.guardrails.input.validate_input", lambda uid, msg: _ok_guard())
    monkeypatch.setattr("app.graph.workflow.build_context", lambda *a, **kw: {"recent_messages": [], "relevant_memory": []})

    from app.graph.router import RoutingDecision
    def fake_classify(q, ctx):
        called.append(q)
        return RoutingDecision(intent="unknown", complexity="simple", agents=[])
    monkeypatch.setattr("app.graph.workflow.classify", fake_classify)
    monkeypatch.setattr("app.guardrails.output.validate_output", lambda r, pii_map=None: {"ok": True, "response": r})
    monkeypatch.setattr("app.memory.session.append_turn", lambda *a, **kw: None)

    run_workflow(1, "sess-3", "Quanto consumi?")
    assert len(called) == 1


# ---------------------------------------------------------------------------
# privacy_violation
# ---------------------------------------------------------------------------

def test_privacy_violation_intent_blocked(monkeypatch):
    monkeypatch.setattr("app.guardrails.input.validate_input", lambda uid, msg: _ok_guard(msg))
    monkeypatch.setattr("app.graph.workflow.build_context", lambda *a, **kw: {"recent_messages": [], "relevant_memory": []})

    from app.graph.router import RoutingDecision
    monkeypatch.setattr("app.graph.workflow.classify", lambda q, ctx: RoutingDecision(intent="privacy_violation", complexity="simple", agents=[]))
    monkeypatch.setattr("app.guardrails.output.validate_output", lambda r, pii_map=None: {"ok": True, "response": r})
    monkeypatch.setattr("app.memory.session.append_turn", lambda *a, **kw: None)

    state = run_workflow(1, "sess-4", "Qual o melhor usuário?")
    assert "outros usuários" in state.get("response", "").lower() or "conta" in state.get("response", "")


def test_privacy_violation_no_chart(monkeypatch):
    monkeypatch.setattr("app.guardrails.input.validate_input", lambda uid, msg: _ok_guard(msg))
    monkeypatch.setattr("app.graph.workflow.build_context", lambda *a, **kw: {"recent_messages": [], "relevant_memory": []})

    from app.graph.router import RoutingDecision
    monkeypatch.setattr("app.graph.workflow.classify", lambda q, ctx: RoutingDecision(intent="privacy_violation", complexity="simple", agents=[]))
    monkeypatch.setattr("app.guardrails.output.validate_output", lambda r, pii_map=None: {"ok": True, "response": r})
    monkeypatch.setattr("app.memory.session.append_turn", lambda *a, **kw: None)

    state = run_workflow(1, "sess-5", "Quem consome mais?")
    assert state.get("chart_data") is None


# ---------------------------------------------------------------------------
# context-passing entre agentes
# ---------------------------------------------------------------------------

def test_first_agent_receives_original_question(monkeypatch):
    received = []
    monkeypatch.setattr("app.guardrails.input.validate_input", lambda uid, msg: _ok_guard(msg))
    monkeypatch.setattr("app.graph.workflow.build_context", lambda *a, **kw: {"recent_messages": [], "relevant_memory": []})

    from app.graph.router import RoutingDecision
    monkeypatch.setattr("app.graph.workflow.classify", lambda q, ctx: RoutingDecision(intent="test", complexity="simple", agents=["forecast"]))

    class _Rec:
        def run(self, q):
            received.append(q)
            class _R:
                response = "ok"
                chart_data = None
                tool_calls = []
            return _R()
    monkeypatch.setattr("app.graph.workflow.load_agent", lambda name, uid: _Rec())
    monkeypatch.setattr("app.services.llms.llm_rapido", None)
    monkeypatch.setattr("app.guardrails.output.validate_output", lambda r, pii_map=None: {"ok": True, "response": r})
    monkeypatch.setattr("app.memory.session.append_turn", lambda *a, **kw: None)

    run_workflow(1, "sess-6", "Qual minha previsão?")
    assert received[0] == "Qual minha previsão?"


def test_second_agent_receives_context_from_first(monkeypatch):
    received = []
    monkeypatch.setattr("app.guardrails.input.validate_input", lambda uid, msg: _ok_guard(msg))
    monkeypatch.setattr("app.graph.workflow.build_context", lambda *a, **kw: {"recent_messages": [], "relevant_memory": []})

    from app.graph.router import RoutingDecision
    monkeypatch.setattr("app.graph.workflow.classify", lambda q, ctx: RoutingDecision(intent="test", complexity="medium", agents=["forecast", "leak"]))

    class _Rec:
        def run(self, q):
            received.append(q)
            class _R:
                response = "resposta do forecast"
                chart_data = None
                tool_calls = []
            return _R()
    monkeypatch.setattr("app.graph.workflow.load_agent", lambda name, uid: _Rec())
    monkeypatch.setattr("app.services.llms.llm_rapido", None)
    monkeypatch.setattr("app.guardrails.output.validate_output", lambda r, pii_map=None: {"ok": True, "response": r})
    monkeypatch.setattr("app.memory.session.append_turn", lambda *a, **kw: None)

    run_workflow(1, "sess-7", "Analise tudo.")
    assert len(received) == 2
    assert "Contexto dos agentes anteriores" in received[1]
    assert "forecast" in received[1]


# ---------------------------------------------------------------------------
# síntese
# ---------------------------------------------------------------------------

def test_synthesis_skipped_with_single_agent(monkeypatch):
    llm_called = []
    monkeypatch.setattr("app.guardrails.input.validate_input", lambda uid, msg: _ok_guard(msg))
    monkeypatch.setattr("app.graph.workflow.build_context", lambda *a, **kw: {"recent_messages": [], "relevant_memory": []})

    from app.graph.router import RoutingDecision
    monkeypatch.setattr("app.graph.workflow.classify", lambda q, ctx: RoutingDecision(intent="test", complexity="simple", agents=["forecast"]))
    monkeypatch.setattr("app.graph.workflow.load_agent", lambda name, uid: _fake_agent(name, "resposta única"))

    class _FakeLLM:
        def invoke(self, *a, **kw):
            llm_called.append(True)
            class _R:
                content = "síntese"
            return _R()
    monkeypatch.setattr("app.services.llms.llm_rapido", _FakeLLM())
    monkeypatch.setattr("app.guardrails.output.validate_output", lambda r, pii_map=None: {"ok": True, "response": r})
    monkeypatch.setattr("app.memory.session.append_turn", lambda *a, **kw: None)

    run_workflow(1, "sess-8", "Previsão?")
    assert not llm_called


def test_synthesis_called_when_two_agents_succeed(monkeypatch):
    llm_called = []
    monkeypatch.setattr("app.guardrails.input.validate_input", lambda uid, msg: _ok_guard(msg))
    monkeypatch.setattr("app.graph.workflow.build_context", lambda *a, **kw: {"recent_messages": [], "relevant_memory": []})

    from app.graph.router import RoutingDecision
    monkeypatch.setattr("app.graph.workflow.classify", lambda q, ctx: RoutingDecision(intent="test", complexity="medium", agents=["forecast", "leak"]))
    monkeypatch.setattr("app.graph.workflow.load_agent", lambda name, uid: _fake_agent(name, f"resposta de {name}"))

    class _FakeLLM:
        def invoke(self, *a, **kw):
            llm_called.append(True)
            class _R:
                content = "síntese unificada"
            return _R()
    monkeypatch.setattr("app.services.llms.llm_rapido", _FakeLLM())
    monkeypatch.setattr("app.guardrails.output.validate_output", lambda r, pii_map=None: {"ok": True, "response": r})
    monkeypatch.setattr("app.memory.session.append_turn", lambda *a, **kw: None)

    state = run_workflow(1, "sess-9", "Analise tudo.")
    assert llm_called
    assert "síntese" in state.get("response", "")


def test_synthesis_fallback_on_llm_failure(monkeypatch):
    monkeypatch.setattr("app.guardrails.input.validate_input", lambda uid, msg: _ok_guard(msg))
    monkeypatch.setattr("app.graph.workflow.build_context", lambda *a, **kw: {"recent_messages": [], "relevant_memory": []})

    from app.graph.router import RoutingDecision
    monkeypatch.setattr("app.graph.workflow.classify", lambda q, ctx: RoutingDecision(intent="test", complexity="medium", agents=["forecast", "leak"]))
    monkeypatch.setattr("app.graph.workflow.load_agent", lambda name, uid: _fake_agent(name, f"resposta de {name}"))

    class _FailLLM:
        def invoke(self, *a, **kw):
            raise RuntimeError("LLM indisponível")
    monkeypatch.setattr("app.services.llms.llm_rapido", _FailLLM())
    monkeypatch.setattr("app.guardrails.output.validate_output", lambda r, pii_map=None: {"ok": True, "response": r})
    monkeypatch.setattr("app.memory.session.append_turn", lambda *a, **kw: None)

    state = run_workflow(1, "sess-10", "Analise tudo.")
    assert state.get("response")
    assert "---" in state.get("response", "")


# ---------------------------------------------------------------------------
# guardrail de saída + histórico
# ---------------------------------------------------------------------------

def test_history_saved_after_response(monkeypatch):
    saved = []
    monkeypatch.setattr("app.guardrails.input.validate_input", lambda uid, msg: _ok_guard(msg))
    monkeypatch.setattr("app.graph.workflow.build_context", lambda *a, **kw: {"recent_messages": [], "relevant_memory": []})

    from app.graph.router import RoutingDecision
    monkeypatch.setattr("app.graph.workflow.classify", lambda q, ctx: RoutingDecision(intent="test", complexity="simple", agents=["forecast"]))
    monkeypatch.setattr("app.graph.workflow.load_agent", lambda name, uid: _fake_agent(name, "resposta ok"))
    monkeypatch.setattr("app.services.llms.llm_rapido", None)
    monkeypatch.setattr("app.guardrails.output.validate_output", lambda r, pii_map=None: {"ok": True, "response": r})
    monkeypatch.setattr("app.memory.session.append_turn", lambda sid, uid, role, content: saved.append(role))

    run_workflow(1, "sess-11", "Quanto consumi?")
    assert "human" in saved
    assert "assistant" in saved


def test_history_save_failure_does_not_crash(monkeypatch):
    monkeypatch.setattr("app.guardrails.input.validate_input", lambda uid, msg: _ok_guard(msg))
    monkeypatch.setattr("app.graph.workflow.build_context", lambda *a, **kw: {"recent_messages": [], "relevant_memory": []})

    from app.graph.router import RoutingDecision
    monkeypatch.setattr("app.graph.workflow.classify", lambda q, ctx: RoutingDecision(intent="test", complexity="simple", agents=["forecast"]))
    monkeypatch.setattr("app.graph.workflow.load_agent", lambda name, uid: _fake_agent(name, "ok"))
    monkeypatch.setattr("app.services.llms.llm_rapido", None)
    monkeypatch.setattr("app.guardrails.output.validate_output", lambda r, pii_map=None: {"ok": True, "response": r})
    monkeypatch.setattr("app.memory.session.append_turn", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("erro de banco")))

    state = run_workflow(1, "sess-12", "Quanto consumi?")
    assert state.get("response")


def test_output_guardrail_redacts_pii(monkeypatch):
    monkeypatch.setattr("app.guardrails.input.validate_input", lambda uid, msg: _ok_guard(msg))
    monkeypatch.setattr("app.graph.workflow.build_context", lambda *a, **kw: {"recent_messages": [], "relevant_memory": []})

    from app.graph.router import RoutingDecision
    monkeypatch.setattr("app.graph.workflow.classify", lambda q, ctx: RoutingDecision(intent="test", complexity="simple", agents=["forecast"]))
    monkeypatch.setattr("app.graph.workflow.load_agent", lambda name, uid: _fake_agent(name, "CPF: 111.222.333-44"))
    monkeypatch.setattr("app.services.llms.llm_rapido", None)
    monkeypatch.setattr("app.memory.session.append_turn", lambda *a, **kw: None)

    state = run_workflow(1, "sess-13", "ok")
    assert "111.222.333-44" not in state.get("response", "")
