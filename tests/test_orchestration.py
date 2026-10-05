"""Testes de orquestração: AgentOutput, execução multi-agente e isolamento de sessão."""

from __future__ import annotations

import pytest

from app.graph.state import AgentOutput
from app.graph.workflow import _execute_node, _respond_node
from app.memory.session import load_history_validated


# ---------------------------------------------------------------------------
# AgentOutput schema
# ---------------------------------------------------------------------------

def test_agent_output_valid():
    out = AgentOutput(agent="forecast", status="success", answer="Vai custar R$ 80.")
    assert out.status == "success"
    assert out.warnings == []
    assert out.chart_data is None


def test_agent_output_with_warning():
    out = AgentOutput(agent="leak", status="error", answer="", warnings=["timeout"])
    assert out.status == "error"
    assert "timeout" in out.warnings


def test_agent_output_serializes():
    out = AgentOutput(agent="habits", status="success", answer="ok")
    d = out.model_dump()
    assert d["agent"] == "habits"
    assert d["confidence"] is None


# ---------------------------------------------------------------------------
# Execução multi-agente (_execute_node)
# ---------------------------------------------------------------------------

def _fake_agent(answer: str, chart=None):
    from app.agents._runtime import AgentResult

    class _Agent:
        def run(self, q):
            return AgentResult(response=answer, chart_data=chart)

    return _Agent()


# _execute_node importa load_agent pelo binding do topo de workflow.py —
# monkeypatchar lá garante que o nó use o fake.
_LOAD_AGENT = "app.graph.workflow.load_agent"


def test_execute_single_agent(monkeypatch):
    monkeypatch.setattr(_LOAD_AGENT, lambda name, uid: _fake_agent("Previsão: 300L"))

    state = {
        "user_id": 1,
        "session_id": "s1",
        "question": "Quanto vou consumir?",
        "selected_agents": ["forecast"],
        "warnings": [],
    }
    result = _execute_node(state)

    assert len(result["agent_results"]) == 1
    assert result["agent_results"][0]["status"] == "success"
    assert "300L" in result["agent_results"][0]["answer"]


def test_execute_two_agents(monkeypatch):
    def _agent(name, uid):
        if name == "forecast":
            return _fake_agent("Conta estimada: R$ 90.")
        return _fake_agent("Nenhum indício de vazamento.")

    monkeypatch.setattr(_LOAD_AGENT, _agent)

    state = {
        "user_id": 1,
        "session_id": "s1",
        "question": "Tenho vazamento e quanto vou gastar?",
        "selected_agents": ["forecast", "leak"],
        "warnings": [],
    }
    result = _execute_node(state)

    assert len(result["agent_results"]) == 2
    agents = {r_["agent"] for r_ in result["agent_results"]}
    assert agents == {"forecast", "leak"}


def test_execute_three_agents(monkeypatch):
    monkeypatch.setattr(_LOAD_AGENT, lambda name, uid: _fake_agent(f"Resposta do {name}."))

    state = {
        "user_id": 1,
        "session_id": "s1",
        "question": "Análise completa.",
        "selected_agents": ["forecast", "leak", "habits"],
        "warnings": [],
    }
    result = _execute_node(state)

    assert len(result["agent_results"]) == 3


def test_execute_unknown_agent_adds_warning(monkeypatch):
    monkeypatch.setattr(_LOAD_AGENT, lambda name, uid: _fake_agent("ok"))

    state = {
        "user_id": 1,
        "session_id": "s1",
        "question": "Pergunta",
        "selected_agents": ["forecast", "agente_inexistente"],
        "warnings": [],
    }
    result = _execute_node(state)

    assert any("agente_inexistente" in w for w in result["warnings"])
    assert len(result["agent_results"]) == 1


def test_execute_agent_error_creates_error_result(monkeypatch):
    class _BrokenAgent:
        def run(self, q):
            raise RuntimeError("banco indisponível")

    monkeypatch.setattr(_LOAD_AGENT, lambda name, uid: _BrokenAgent())

    state = {
        "user_id": 1,
        "session_id": "s1",
        "question": "Pergunta",
        "selected_agents": ["forecast"],
        "warnings": [],
    }
    result = _execute_node(state)

    assert result["agent_results"][0]["status"] == "error"
    assert "banco indisponível" in result["warnings"][0]


def test_execute_collects_all_results(monkeypatch):
    monkeypatch.setattr(_LOAD_AGENT, lambda name, uid: _fake_agent(f"ok {name}"))

    state = {
        "user_id": 1,
        "session_id": "s1",
        "question": "X",
        "selected_agents": ["forecast", "leak", "habits"],
        "warnings": [],
    }
    result = _execute_node(state)

    assert all(r_["status"] == "success" for r_ in result["agent_results"])


# ---------------------------------------------------------------------------
# _respond_node
# ---------------------------------------------------------------------------

def _state_with_results(results: list[dict], selected: list[str] | None = None) -> dict:
    return {
        "user_id": 1,
        "session_id": "s1",
        "question": "Pergunta",
        "selected_agents": selected if selected is not None else [r["agent"] for r in results],
        "agent_results": results,
    }


def test_respond_single_agent_uses_answer():
    state = _state_with_results(
        [AgentOutput(agent="forecast", status="success", answer="Estimativa: 300L.").model_dump()]
    )
    result = _respond_node(state)
    assert "300L" in result["response"]


def test_respond_single_agent_propagates_chart():
    chart = {"data": [{"x": [1], "y": [2]}]}
    state = _state_with_results(
        [AgentOutput(agent="forecast", status="success", answer="ok", chart_data=chart).model_dump()]
    )
    result = _respond_node(state)
    assert result["chart_data"] == chart


def test_respond_multi_agent_concatenates():
    results = [
        AgentOutput(agent="forecast", status="success", answer="Conta: R$ 90.").model_dump(),
        AgentOutput(agent="habits", status="success", answer="Você tem 3 hábitos.").model_dump(),
    ]
    state = _state_with_results(results)
    result = _respond_node(state)

    assert "R$ 90" in result["response"]
    assert "3 hábitos" in result["response"]


def test_respond_no_agents_returns_fallback():
    state = _state_with_results([], selected=[])
    result = _respond_node(state)
    assert "Não entendi" in result["response"]


def test_respond_all_errors_returns_error_message():
    results = [
        AgentOutput(agent="forecast", status="error", answer="").model_dump(),
        AgentOutput(agent="leak", status="error", answer="").model_dump(),
    ]
    state = _state_with_results(results)
    result = _respond_node(state)
    assert "Não foi possível" in result["response"]


# ---------------------------------------------------------------------------
# Isolamento de sessão
# ---------------------------------------------------------------------------

def test_history_owner_can_access(monkeypatch):
    doc = {"user_id": 42, "messages": [{"role": "human", "content": "oi"}]}
    monkeypatch.setattr(
        "app.memory.session._col",
        lambda: type("C", (), {"find_one": lambda self, q, proj=None: doc})(),
    )
    msgs = load_history_validated(user_id=42, session_id="any")
    assert len(msgs) == 1


def test_other_user_cannot_access_session(monkeypatch):
    doc = {"user_id": 42, "messages": [{"role": "human", "content": "privado"}]}
    monkeypatch.setattr(
        "app.memory.session._col",
        lambda: type("C", (), {"find_one": lambda self, q, proj=None: doc})(),
    )
    msgs = load_history_validated(user_id=99, session_id="any")
    assert msgs == []


def test_nonexistent_session_returns_empty(monkeypatch):
    monkeypatch.setattr(
        "app.memory.session._col",
        lambda: type("C", (), {"find_one": lambda self, q, proj=None: None})(),
    )
    msgs = load_history_validated(user_id=1, session_id="inexistente")
    assert msgs == []
