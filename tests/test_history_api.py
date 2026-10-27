"""Rotas /chat e /sessions: autenticação JWT e histórico, com MongoDB real."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.memory import session as memory
from app.routes import chat as chat_route
from app.routes import sessions as sessions_route
from app.services import session_meta
from tests.conftest import JWT_SECRET, auth_header, make_token


@pytest.fixture
def client(mongo_db, monkeypatch):
    monkeypatch.setattr("app.auth.get_settings", lambda: SimpleNamespace(jwt_secret=JWT_SECRET))

    def fake_workflow(user_id, session_id, question):
        memory.append_turn(session_id, user_id, "human", question)
        memory.append_turn(session_id, user_id, "assistant", f"Resposta para: {question}")
        return {"response": f"Resposta para: {question}", "selected_agents": ["habits"]}

    monkeypatch.setattr(chat_route, "run_workflow", fake_workflow)
    monkeypatch.setattr(sessions_route, "close_session", lambda session_id, user_id: None)

    app = FastAPI()
    app.include_router(chat_route.router)
    app.include_router(sessions_route.router)
    return TestClient(app)


def _chat(client, user_id, message="Como diminuir meu gasto?", session_id=None):
    body = {"message": message}
    if session_id:
        body["session_id"] = session_id
    return client.post("/chat", json=body, headers=auth_header(user_id))


# --- autenticação -----------------------------------------------------------


@pytest.mark.parametrize(
    "path, method",
    [("/sessions", "get"), (f"/sessions/{ObjectId()}/messages", "get"), (f"/sessions/{ObjectId()}/close", "post")],
)
def test_routes_require_token(client, path, method):
    response = getattr(client, method)(path)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_chat_requires_token(client):
    assert client.post("/chat", json={"message": "oi"}).status_code == 401


def test_rejects_invalid_tokens(client):
    expired = make_token(7, expires_in=-10)
    wrong_secret = make_token(7, secret="outro-segredo-com-mais-de-32-caracteres!!")
    no_exp = jwt.encode({"sub": "7"}, JWT_SECRET, algorithm="HS256")
    unsigned = jwt.encode({"sub": "7", "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, None, algorithm="none")
    bad_sub = make_token("abc")
    negative_sub = make_token(-3)

    for token in (expired, wrong_secret, no_exp, unsigned, bad_sub, negative_sub, "lixo"):
        response = client.get("/sessions", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401, token


def test_secret_not_configured_blocks_every_request(client, monkeypatch):
    monkeypatch.setattr("app.auth.get_settings", lambda: SimpleNamespace(jwt_secret=None))
    assert client.get("/sessions", headers=auth_header(7)).status_code == 503

    monkeypatch.setattr("app.auth.get_settings", lambda: SimpleNamespace(jwt_secret="curto"))
    assert client.get("/sessions", headers=auth_header(7)).status_code == 503


def test_user_id_in_body_or_query_is_ignored(client):
    session_id = _chat(client, 7).json()["session_id"]

    response = client.get("/sessions?user_id=7", headers=auth_header(8))

    assert response.json()["sessions"] == []
    assert memory.session_belongs_to_user(7, session_id)


# --- /chat e session_id gerado pelo servidor --------------------------------


def test_chat_creates_session_with_server_generated_id(client, mongo_db):
    response = _chat(client, 7)

    assert response.status_code == 200
    session_id = response.json()["session_id"]
    assert ObjectId.is_valid(session_id)
    assert mongo_db.chat_sessions.count_documents({"_id": ObjectId(session_id), "user_id": 7}) == 1


def test_chat_continues_own_session(client, mongo_db):
    session_id = _chat(client, 7).json()["session_id"]

    again = _chat(client, 7, "e a rotina?", session_id=session_id)

    assert again.json()["session_id"] == session_id
    assert len(mongo_db.chat_sessions.find_one({"_id": ObjectId(session_id)})["messages"]) == 4


@pytest.mark.parametrize("fake_id", ["minha-sessao", "123", str(ObjectId())])
def test_chat_rejects_client_chosen_session_id(client, mongo_db, fake_id):
    response = _chat(client, 7, session_id=fake_id)

    assert response.status_code == 404
    assert mongo_db.chat_sessions.count_documents({}) == 0


def test_chat_cannot_write_into_other_users_session(client, mongo_db):
    session_id = _chat(client, 7).json()["session_id"]

    response = _chat(client, 8, "intruso", session_id=session_id)

    assert response.status_code == 404
    assert len(mongo_db.chat_sessions.find_one({"_id": ObjectId(session_id)})["messages"]) == 2


# --- listagem e mensagens ---------------------------------------------------


def test_listing_returns_llm_meta_for_mobile_and_web(client):
    session_id = _chat(client, 7, "Crie uma rotina mais sustentável.").json()["session_id"]

    class FakeModel:
        def invoke(self, prompt):
            return SimpleNamespace(
                content='```json\n{"title": "Definir rotina nova", "preview": "Rotina para diminuir 12% de gastos", "icon": "routine"}\n```'
            )

    session_meta.llms.llm_rapido = FakeModel()
    try:
        session_meta.refresh_session_meta(7, session_id, "Crie uma rotina mais sustentável.", "Resposta")
    finally:
        del session_meta.llms.__dict__["llm_rapido"]

    body = client.get("/sessions?limit=4", headers=auth_header(7)).json()

    assert body["total"] == 1
    item = body["sessions"][0]
    assert item["session_id"] == session_id
    assert item["title"] == "Definir rotina nova"
    assert item["preview"] == "Rotina para diminuir 12% de gastos"
    assert item["icon"] == "routine"
    assert item["created_at"] and item["updated_at"] and item["is_open"] is True


def test_listing_paginates_with_total_for_ver_todos(client):
    for index in range(5):
        _chat(client, 7, f"pergunta {index}")

    page = client.get("/sessions?limit=2&offset=2", headers=auth_header(7)).json()

    assert page["total"] == 5 and len(page["sessions"]) == 2
    assert client.get("/sessions?limit=0", headers=auth_header(7)).status_code == 422
    assert client.get("/sessions?limit=101", headers=auth_header(7)).status_code == 422


def test_messages_only_for_owner(client):
    session_id = _chat(client, 7, "oi").json()["session_id"]

    own = client.get(f"/sessions/{session_id}/messages", headers=auth_header(7))
    foreign = client.get(f"/sessions/{session_id}/messages", headers=auth_header(8))
    missing = client.get(f"/sessions/{ObjectId()}/messages", headers=auth_header(7))
    invalid = client.get("/sessions/nao-e-id/messages", headers=auth_header(7))

    assert [m["role"] for m in own.json()["messages"]] == ["user", "bot"]
    assert foreign.status_code == missing.status_code == invalid.status_code == 404
    assert foreign.json() == missing.json()


def test_close_marks_session_and_blocks_other_users(client, mongo_db):
    session_id = _chat(client, 7).json()["session_id"]

    assert client.post(f"/sessions/{session_id}/close", headers=auth_header(8)).status_code == 404
    assert mongo_db.chat_sessions.find_one({"_id": ObjectId(session_id)})["is_open"] is True

    assert client.post(f"/sessions/{session_id}/close", headers=auth_header(7)).status_code == 200
    closed = mongo_db.chat_sessions.find_one({"_id": ObjectId(session_id)})
    assert closed["is_open"] is False and closed["is_active"] is False
