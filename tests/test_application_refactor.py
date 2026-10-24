"""Confirma contratos de privacidade e memória após simplificar as chamadas."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.guardrails.output import validate_output
from app.memory import long_term, session


@pytest.mark.parametrize("response", ["", "   "])
def test_output_still_rejects_empty_response(response):
    assert validate_output(response)["ok"] is False


def test_output_removes_email_and_does_not_restore_original_token_value():
    response = "Contato: pessoa@example.com. CPF: [PII_CPF_abc123]."
    result = validate_output(response, {"[PII_CPF_abc123]": "123.456.789-00"})

    assert result["ok"] is True
    assert "pessoa@example.com" not in result["response"]
    assert "123.456.789-00" not in result["response"]
    assert "[EMAIL OMITIDO]" in result["response"]
    assert "[CPF OMITIDO]" in result["response"]


def test_output_still_rejects_credentials():
    result = validate_output("senha: exemplo-sintetico")

    assert result == {"ok": False, "reason": "Resposta contém possível credencial."}


@pytest.fixture
def conversations(monkeypatch):
    client = MagicMock()
    collection = client["delta_test_conversations"]["conversations"]
    monkeypatch.setattr(session, "get_app_client", lambda: client)
    monkeypatch.setattr(
        session, "get_settings",
        lambda: SimpleNamespace(mongo_db_app="delta_test_conversations"),
    )

    return collection


@pytest.mark.parametrize("owner,expected", [(7, [{"role": "human", "content": "oi"}]), (8, [])])
def test_session_history_uses_configured_database_and_checks_owner(conversations, owner, expected):
    conversations.find_one.return_value = {
        "user_id": owner,
        "messages": [{"role": "human", "content": "oi"}],
    }

    assert session.load_history_validated(7, "session-test") == expected

    conversations.find_one.assert_called_once_with(
        {"session_id": "session-test"}, {"_id": 0, "user_id": 1, "messages": 1},
    )


def test_appending_to_another_users_session_does_not_write(conversations):
    conversations.find_one.return_value = {"user_id": 8}

    with pytest.raises(ValueError, match="outro usuário"):
        session.append_turn("session-test", 7, "human", "oi")

    conversations.update_one.assert_not_called()


def test_appending_to_owned_session_preserves_message(conversations):
    conversations.find_one.return_value = {"user_id": 7}

    session.append_turn("session-test", 7, "human", "oi")

    query, update = conversations.update_one.call_args.args
    assert query == {"session_id": "session-test"}
    assert update["$setOnInsert"]["user_id"] == 7
    assert update["$push"]["messages"]["content"] == "oi"
    assert update["$push"]["messages"]["timestamp"].utcoffset() is not None


def test_session_list_remains_scoped_to_user(conversations):
    conversations.find.return_value = [{"session_id": "session-test"}]

    assert session.get_sessions_for_user(7) == [{"session_id": "session-test"}]

    conversations.find.assert_called_once_with(
        {"user_id": 7}, {"_id": 0, "session_id": 1, "created_at": 1},
    )


def test_memory_client_reads_settings_when_cache_is_rebuilt(monkeypatch):
    factory = MagicMock()
    settings = SimpleNamespace(qdrant_url="http://127.0.0.1:6333", qdrant_api_key=None)
    monkeypatch.setattr("qdrant_client.QdrantClient", factory)
    monkeypatch.setattr(long_term, "get_settings", lambda: settings)
    long_term._qdrant.cache_clear()

    try:
        long_term._qdrant()
        factory.assert_called_once_with(url="http://127.0.0.1:6333", api_key=None)

        settings.qdrant_url = "http://127.0.0.1:6334"
        long_term._qdrant.cache_clear()
        long_term._qdrant()

        assert factory.call_args.kwargs["url"] == "http://127.0.0.1:6334"
    finally:
        long_term._qdrant.cache_clear()
