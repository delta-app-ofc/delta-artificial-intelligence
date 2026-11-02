"""Sugestões de próximas perguntas: regras e rotas, sem LLM nem banco reais."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.graph.suggestions import MAX_SUGGESTIONS, initial_suggestions, suggest_next_questions
from app.routes import chat as chat_route
from tests.conftest import JWT_SECRET, auth_header, auth_settings


def test_suggestions_follow_the_topics_and_never_exceed_three():
    out = suggest_next_questions(["habits", "forecast", "leak"], "residential")
    assert 1 <= len(out) <= MAX_SUGGESTIONS
    assert len(set(out)) == len(out)


def test_it_does_not_repeat_the_question_just_asked():
    out = suggest_next_questions(["forecast"], "residential", "e se meu consumo diário cair 10%?")
    assert "E se meu consumo diário cair 10%?" not in out and out


def test_no_agent_falls_back_to_the_starting_questions():
    assert suggest_next_questions([], "residential") == initial_suggestions("residential")


def test_organization_never_gets_habit_questions():
    every = suggest_next_questions(["habits", "consumption", "forecast"], "organizational")
    start = initial_suggestions("organizational")
    for text in every + start:
        assert "hábito" not in text.lower() and "roupa" not in text.lower()


def test_unknown_profile_uses_residential_questions():
    assert initial_suggestions(None) == initial_suggestions("residential")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("app.auth.get_settings", lambda: auth_settings(jwt_secret=JWT_SECRET))
    monkeypatch.setattr(chat_route, "resolve_access_kind", lambda user_id: "organizational")
    app = FastAPI()
    app.include_router(chat_route.router)
    return TestClient(app)


def test_route_requires_token_and_follows_the_profile(client):
    assert client.get("/chat/suggestions").status_code == 401
    out = client.get("/chat/suggestions", headers=auth_header(7))
    assert out.status_code == 200
    assert out.json()["suggestions"] == initial_suggestions("organizational")


def test_route_survives_profile_lookup_failure(client, monkeypatch):
    def broken(user_id):
        raise RuntimeError("banco fora")

    monkeypatch.setattr(chat_route, "resolve_access_kind", broken)
    out = client.get("/chat/suggestions", headers=auth_header(7))
    assert out.json()["suggestions"] == initial_suggestions(None)
