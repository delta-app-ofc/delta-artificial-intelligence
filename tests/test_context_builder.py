"""Testes do Context Builder: histórico MongoDB + memória Qdrant condicional."""

from __future__ import annotations

import pytest

from app.graph.context import RECENT_TURNS, build_context


def test_returns_recent_messages(monkeypatch):
    messages = [{"role": "human", "content": f"msg {i}"} for i in range(8)]
    monkeypatch.setattr("app.memory.session.load_history_validated", lambda uid, sid: messages)

    ctx = build_context(user_id=1, session_id="s1", question="qual meu consumo?")

    assert len(ctx["recent_messages"]) == RECENT_TURNS
    assert ctx["recent_messages"][-1]["content"] == "msg 7"


def test_qdrant_not_called_for_common_question(monkeypatch):
    monkeypatch.setattr("app.memory.session.load_history_validated", lambda uid, sid: [])
    called = []

    def _fail(*a, **kw):
        called.append(True)
        return []

    monkeypatch.setattr("app.memory.long_term.search_memory", _fail)

    build_context(user_id=1, session_id="s1", question="quanto vou gastar este mês?")

    assert not called, "Qdrant não deve ser chamado para perguntas sem referência ao passado"


def test_qdrant_called_when_question_references_past(monkeypatch):
    monkeypatch.setattr("app.memory.session.load_history_validated", lambda uid, sid: [])
    called = []

    def _search(uid, q, **kw):
        called.append(True)
        return ["memória relevante"]

    monkeypatch.setattr("app.memory.long_term.search_memory", _search)

    ctx = build_context(user_id=1, session_id="s1", question="você disse que eu consumia muito antes")

    assert called, "Qdrant deve ser chamado quando a pergunta referencia sessões anteriores"
    assert ctx["relevant_memory"] == ["memória relevante"]


def test_empty_history(monkeypatch):
    monkeypatch.setattr("app.memory.session.load_history_validated", lambda uid, sid: [])

    ctx = build_context(user_id=1, session_id="s1", question="algo")

    assert ctx["recent_messages"] == []
    assert ctx["relevant_memory"] == []


def test_no_relevant_memory_when_qdrant_not_triggered(monkeypatch):
    monkeypatch.setattr(
        "app.memory.session.load_history_validated",
        lambda uid, sid: [{"role": "human", "content": "oi"}],
    )

    ctx = build_context(user_id=1, session_id="s1", question="meus hábitos")

    assert len(ctx["recent_messages"]) == 1
    assert ctx["relevant_memory"] == []


def test_mongo_error_returns_empty_recent(monkeypatch):
    def _raise(uid, sid):
        raise ConnectionError("mongo indisponível")

    monkeypatch.setattr("app.memory.session.load_history_validated", _raise)

    ctx = build_context(user_id=1, session_id="s1", question="algo")

    assert ctx["recent_messages"] == []


def test_qdrant_error_returns_empty_memory(monkeypatch):
    monkeypatch.setattr(
        "app.memory.session.load_history_validated",
        lambda uid, sid: [{"role": "human", "content": "msg"}],
    )

    def _raise(uid, q, **kw):
        raise ConnectionError("qdrant indisponível")

    monkeypatch.setattr("app.memory.long_term.search_memory", _raise)

    ctx = build_context(
        user_id=1, session_id="s1", question="você falou algo na semana passada?"
    )

    assert len(ctx["recent_messages"]) == 1
    assert ctx["relevant_memory"] == []
