"""Testes do Router Agent: classificação de intenção, complexidade e agentes."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from app.graph.router import AGENT_REGISTRY, RoutingDecision, classify


def _mock_llm(content: str):
    class _FakeLLM:
        def invoke(self, messages, **kwargs):
            return AIMessage(content=content)

    return _FakeLLM()


# classify() importa llm_rapido de app.services.llms dentro da função —
# monkeypatchar lá garante que o import local pegue o objeto correto.
_LLM_PATH = "app.services.llms.llm_rapido"


def test_simple_forecast(monkeypatch):
    payload = '{"intent": "consumption_forecast", "complexity": "simple", "agents": ["forecast"]}'
    monkeypatch.setattr(_LLM_PATH, _mock_llm(payload))

    decision = classify("Quanto vou gastar este mês?", {})

    assert decision.intent == "consumption_forecast"
    assert decision.complexity == "simple"
    assert decision.agents == ["forecast"]


def test_medium_habits_and_forecast(monkeypatch):
    payload = '{"intent": "habits_impact", "complexity": "medium", "agents": ["habits", "forecast"]}'
    monkeypatch.setattr(_LLM_PATH, _mock_llm(payload))

    decision = classify("Meus hábitos estão afetando minha conta?", {})

    assert decision.complexity == "medium"
    assert set(decision.agents) == {"habits", "forecast"}


def test_complex_full_analysis(monkeypatch):
    payload = '{"intent": "full_analysis", "complexity": "complex", "agents": ["forecast", "leak", "habits"]}'
    monkeypatch.setattr(_LLM_PATH, _mock_llm(payload))

    decision = classify("Analise tudo: consumo, hábitos e vazamento.", {})

    assert decision.complexity == "complex"
    assert len(decision.agents) == 3


def test_unknown_intent_returns_empty_agents(monkeypatch):
    payload = '{"intent": "unknown", "complexity": "simple", "agents": []}'
    monkeypatch.setattr(_LLM_PATH, _mock_llm(payload))

    decision = classify("Como vai o Brasil?", {})

    assert decision.intent == "unknown"
    assert decision.agents == []


def test_nonexistent_agent_is_filtered_out(monkeypatch):
    payload = '{"intent": "test", "complexity": "simple", "agents": ["forecast", "nonexistent_agent"]}'
    monkeypatch.setattr(_LLM_PATH, _mock_llm(payload))

    decision = classify("Alguma pergunta", {})

    assert "nonexistent_agent" not in decision.agents
    assert "forecast" in decision.agents


def test_invalid_llm_response_returns_fallback(monkeypatch):
    monkeypatch.setattr(_LLM_PATH, _mock_llm("isso não é JSON"))

    decision = classify("Qualquer coisa", {})

    assert decision.intent == "unknown"
    assert decision.agents == []
    assert decision.complexity == "simple"


def test_routing_decision_schema_validates():
    d = RoutingDecision(intent="test", complexity="simple", agents=["forecast"])
    assert d.agents == ["forecast"]


def test_agent_registry_contains_known_agents():
    assert "forecast" in AGENT_REGISTRY
    assert "leak" in AGENT_REGISTRY
    assert "habits" in AGENT_REGISTRY


def test_classify_uses_context_history(monkeypatch):
    payload = '{"intent": "consumption_forecast", "complexity": "simple", "agents": ["forecast"]}'

    captured: list[list] = []

    class _CaptureLLM:
        def invoke(self, messages, **kwargs):
            captured.append(messages)
            return AIMessage(content=payload)

    monkeypatch.setattr(_LLM_PATH, _CaptureLLM())

    context = {
        "recent_messages": [
            {"role": "human", "content": "Qual meu consumo?"},
            {"role": "assistant", "content": "Seu consumo foi de 300L."},
        ],
        "relevant_memory": [],
    }
    classify("E quanto vou gastar?", context)

    assert captured, "llm_rapido.invoke não foi chamado"
    user_msg = captured[0][-1]
    assert "Qual meu consumo?" in user_msg.content
