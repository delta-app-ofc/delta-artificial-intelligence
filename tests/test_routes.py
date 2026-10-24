"""Testes das rotas FastAPI com TestClient e workflow monkeypatched."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    from app.graph.workflow import GraphState

    def fake_workflow(user_id, session_id, question, **kwargs):
        return GraphState(
            user_id=user_id,
            session_id=session_id,
            question=question,
            response="resposta de teste",
            agent_used="forecast",
            chart_data=None,
            agent_results=[],
            warnings=[],
            recent_messages=[],
            relevant_memory=[],
            intent="consumption_forecast",
            complexity="simple",
            selected_agents=["forecast"],
            pii_map={},
            _blocked=False,
            skip_guardrail_input=False,
        )

    monkeypatch.setattr("app.graph.workflow.run_workflow", fake_workflow)
    monkeypatch.setattr(
        "app.guardrails.input.validate_input",
        lambda uid, msg: {"ok": True, "message": msg, "pii_map": {}},
    )
    monkeypatch.setattr(
        "app.guardrails.output.validate_output",
        lambda r, **kw: {"ok": True, "response": r},
    )
    monkeypatch.setattr("app.memory.session.append_turn", lambda *a, **kw: None)

    from app.main import app
    return TestClient(app)


def test_chat_ok(client):
    resp = client.post("/chat", json={"user_id": 1, "message": "Quanto consumi?"})
    assert resp.status_code == 200
    data = resp.json()
    assert "response" in data
    assert isinstance(data["agents_used"], list)
    assert "session_id" in data


def test_chat_blocked_by_guardrail(monkeypatch):
    monkeypatch.setattr(
        "app.routes.chat.validate_input",
        lambda uid, msg: {"ok": False, "reason": "Mensagem inválida."},
    )
    from app.main import app
    c = TestClient(app)
    resp = c.post("/chat", json={"user_id": 1, "message": "conteúdo bloqueado"})
    assert resp.status_code == 422


def test_chat_invalid_user_id(client):
    resp = client.post("/chat", json={"user_id": 0, "message": "teste"})
    assert resp.status_code == 422


def test_chat_state_response_missing(monkeypatch):
    from app.graph.workflow import GraphState

    def workflow_without_response(user_id, session_id, question, **kwargs):
        return GraphState(
            user_id=user_id,
            session_id=session_id,
            question=question,
            response="",
            agent_used="",
            chart_data=None,
            agent_results=[],
            warnings=[],
            recent_messages=[],
            relevant_memory=[],
            intent="",
            complexity="simple",
            selected_agents=[],
            pii_map={},
            _blocked=False,
            skip_guardrail_input=False,
        )

    monkeypatch.setattr("app.graph.workflow.run_workflow", workflow_without_response)
    monkeypatch.setattr(
        "app.routes.chat.validate_input",
        lambda uid, msg: {"ok": True, "message": msg, "pii_map": {}},
    )
    monkeypatch.setattr(
        "app.routes.chat.validate_output",
        lambda r, **kw: {"ok": False, "reason": "Resposta vazia."},
    )
    monkeypatch.setattr("app.memory.session.append_turn", lambda *a, **kw: None)

    from app.main import app
    c = TestClient(app)
    resp = c.post("/chat", json={"user_id": 1, "message": "teste"})
    assert resp.status_code == 500
    assert "processar" in resp.json().get("detail", "").lower()


def test_cors_headers_present(client):
    resp = client.options("/chat", headers={"Origin": "http://localhost:3000"})
    assert "access-control-allow-origin" in resp.headers


def test_health_returns_status(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert "status" in resp.json()


def test_close_error_is_safe(monkeypatch):
    monkeypatch.setattr(
        "app.routes.sessions.close_session",
        lambda sid, uid: (_ for _ in ()).throw(RuntimeError("falha interna")),
    )
    from app.main import app
    c = TestClient(app)
    resp = c.post("/sessions/sessao-xyz/close?user_id=1")
    assert resp.status_code == 500
    detail = resp.json().get("detail", "")
    assert "falha interna" not in detail
    assert "encerrar" in detail.lower()
