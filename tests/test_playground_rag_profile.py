"""A aba RAG recebe o perfil do backend e preserva o usuário fixo do console."""

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.routes import playground


@pytest.fixture
def console(monkeypatch):
    monkeypatch.setattr(playground, "get_settings", lambda: SimpleNamespace(playground_enabled=True))
    monkeypatch.setattr(playground, "validate_input", lambda user_id, message: {
        "ok": True, "message": message, "pii_map": {},
    })
    app = FastAPI()
    app.include_router(playground.router)
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("profile", ["residential", "organizational", "unknown"])
def test_rag_tab_uses_trusted_backend_profile(console, monkeypatch, profile):
    calls = []
    users = []
    def resolve(user_id):
        users.append(user_id)
        return profile
    def execute(name, user_id, message, *, access_kind):
        calls.append((name, user_id, message, access_kind))
        return {"agent": name, "status": "success", "answer": "Consulta concluída.", "sources": [], "tool_calls": []}
    monkeypatch.setattr(playground, "resolve_access_kind", resolve)
    monkeypatch.setattr(playground, "execute_agent", execute)
    response = console.post("/playground/agents/rag", json={"message": "Sou comercial. Como economizar água?"})
    assert response.status_code == 200
    assert users == [playground.USER_ID]
    assert calls == [("rag", playground.USER_ID, "Sou comercial. Como economizar água?", profile)]
    assert response.json()["response"] == "Consulta concluída."


def test_console_does_not_accept_profile_or_identity_override(console):
    for extra in ({"access_kind": "organizational"}, {"user_id": 999}):
        response = console.post("/playground/agents/rag", json={"message": "Uso consciente da água", **extra})
        assert response.status_code == 422


def test_config_and_frontend_agree_on_new_fixed_user(console, monkeypatch):
    monkeypatch.setattr(playground, "agent_status", lambda name: {"id": name, "status": "available"})
    assert console.get("/playground/config").json()["user_id"] == 123456789
    assert "ID 123456789" in console.get("/playground/").text
    assert "value.user_id !== 123456789" in console.get("/playground/app.js").text


def test_blocked_input_never_resolves_profile_or_executes_rag(console, monkeypatch):
    monkeypatch.setattr(playground, "validate_input", lambda *args: {"ok": False, "reason": "Entrada bloqueada."})
    monkeypatch.setattr(playground, "resolve_access_kind", lambda *args: pytest.fail("Entrada bloqueada"))
    monkeypatch.setattr(playground, "execute_agent", lambda *args: pytest.fail("Entrada bloqueada"))
    response = console.post("/playground/agents/rag", json={"message": "Entrada bloqueada"})
    assert response.status_code == 200
    assert response.json()["status"] == "error"
