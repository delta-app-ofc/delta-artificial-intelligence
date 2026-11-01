"""Fixtures dos testes de isolamento: a API com JWT sobre o MongoDB real de tests/conftest.py."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.isolation.helpers import JWT_SECRET, auth_settings


@pytest.fixture
def jwt_secret(monkeypatch):
    monkeypatch.setattr("app.auth.get_settings", lambda: auth_settings(jwt_secret=JWT_SECRET))


@pytest.fixture
def api(mongo_db, jwt_secret, monkeypatch):
    """API de chat e sessões com o fluxo de IA substituído por um que só grava a conversa."""
    from app.memory import session as memory
    from app.routes import chat as chat_route
    from app.routes import sessions as sessions_route

    def fake_workflow(user_id, session_id, question):
        memory.append_turn(session_id, user_id, "human", question)
        memory.append_turn(session_id, user_id, "assistant", f"Resposta para: {question}")
        return {"response": f"Resposta para: {question}", "selected_agents": []}

    monkeypatch.setattr(chat_route, "run_workflow", fake_workflow)
    monkeypatch.setattr(sessions_route, "close_session", lambda session_id, user_id: None)

    app = FastAPI()
    app.include_router(chat_route.router)
    app.include_router(sessions_route.router)
    return TestClient(app)
