from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.memory import session as session_memory
from app.routes import sessions as sessions_route


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(sessions_route.router)
    return TestClient(app)


def test_shorten_keeps_short_text():
    assert session_memory._shorten("Definir rotina nova", 40) == "Definir rotina nova"


def test_shorten_truncates_and_collapses_spaces():
    result = session_memory._shorten("Rotina   para\ndiminuir 12% de gastos poderia ser feita", 20)
    assert len(result) == 20
    assert result.endswith("…")
    assert "\n" not in result


def test_list_sessions_returns_title_preview_and_total(monkeypatch):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    captured = {}

    def fake_get(user_id, limit, offset):
        captured.update(user_id=user_id, limit=limit, offset=offset)
        return [
            {
                "session_id": "s1",
                "title": "Definir rotina nova",
                "preview": "Rotina para diminuir 12%…",
                "created_at": now,
                "updated_at": now,
            }
        ]

    monkeypatch.setattr(sessions_route, "get_sessions_for_user", fake_get)
    monkeypatch.setattr(sessions_route, "count_sessions_for_user", lambda user_id: 7)

    response = _client().get("/users/3/sessions?limit=4")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 7
    assert body["sessions"][0]["title"] == "Definir rotina nova"
    assert body["sessions"][0]["preview"].startswith("Rotina")
    assert captured == {"user_id": 3, "limit": 4, "offset": 0}


def test_list_sessions_rejects_invalid_limit():
    assert _client().get("/users/3/sessions?limit=0").status_code == 422
    assert _client().get("/users/3/sessions?limit=101").status_code == 422
