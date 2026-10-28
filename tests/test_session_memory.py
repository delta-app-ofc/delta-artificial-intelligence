"""Memória de sessão em `chat_sessions`, com MongoDB real e o validador oficial."""

import time

import pytest
from bson import ObjectId

from app.memory import session as memory


def _turn(user_id, session_id, question, answer):
    memory.append_turn(session_id, user_id, "human", question)
    memory.append_turn(session_id, user_id, "assistant", answer)


def test_create_session_follows_official_schema(mongo_db):
    session_id = memory.create_session(7)

    doc = mongo_db.chat_sessions.find_one({"_id": ObjectId(session_id)})
    assert doc["user_id"] == 7
    assert doc["is_open"] is True and doc["is_active"] is True and doc["is_deleted"] is False
    assert doc["messages"] == []
    assert doc["started_at"] <= doc["last_activity_at"]


def test_append_turn_maps_roles_and_accepts_validator(mongo_db):
    session_id = memory.create_session(7)
    _turn(7, session_id, "Como diminuir meu gasto?", "Reduza o tempo de banho.")

    doc = mongo_db.chat_sessions.find_one({"_id": ObjectId(session_id)})
    first, second = doc["messages"]
    assert (first["role"], second["role"]) == ("user", "bot")
    assert first["content_type"] == "text" and first["api_status_code"] == 200
    assert first["sent_at"] and second["content"] == "Reduza o tempo de banho."
    assert doc["last_activity_at"] >= doc["started_at"]


def test_append_turn_rejects_other_user_without_changes(mongo_db):
    session_id = memory.create_session(7)

    with pytest.raises(ValueError):
        memory.append_turn(session_id, 8, "human", "intruso")

    assert mongo_db.chat_sessions.find_one({"_id": ObjectId(session_id)})["messages"] == []


@pytest.mark.parametrize("session_id", ["abc", "", "x" * 24, str(ObjectId())])
def test_append_turn_rejects_unknown_or_invalid_session(mongo_db, session_id):
    with pytest.raises(ValueError):
        memory.append_turn(session_id, 7, "human", "oi")


def test_append_turn_rejects_invalid_role(mongo_db):
    session_id = memory.create_session(7)
    with pytest.raises(ValueError):
        memory.append_turn(session_id, 7, "system", "oi")


def test_history_is_only_visible_to_owner(mongo_db):
    session_id = memory.create_session(7)
    _turn(7, session_id, "pergunta", "resposta")

    owner = memory.load_history_validated(7, session_id)
    assert [m["role"] for m in owner] == ["user", "bot"]
    assert memory.load_history_validated(8, session_id) == []
    assert memory.load_history_validated(7, "invalido") == []
    assert memory.session_belongs_to_user(7, session_id) is True
    assert memory.session_belongs_to_user(8, session_id) is False


def test_listing_is_sorted_paginated_and_isolated(mongo_db):
    ids = []
    for index in range(5):
        session_id = memory.create_session(7)
        _turn(7, session_id, f"pergunta {index}", f"resposta {index}")
        ids.append(session_id)
        time.sleep(0.01)
    other = memory.create_session(8)
    _turn(8, other, "de outro usuário", "resposta")

    first_page = memory.get_sessions_for_user(7, limit=2, offset=0)
    second_page = memory.get_sessions_for_user(7, limit=2, offset=2)

    assert [s["session_id"] for s in first_page] == [ids[4], ids[3]]
    assert [s["session_id"] for s in second_page] == [ids[2], ids[1]]
    assert memory.count_sessions_for_user(7) == 5
    assert other not in {s["session_id"] for s in memory.get_sessions_for_user(7, limit=100)}


def test_listing_skips_empty_and_deleted_sessions(mongo_db):
    memory.create_session(7)  # vazia: não aparece
    deleted = memory.create_session(7)
    _turn(7, deleted, "pergunta", "resposta")
    mongo_db.chat_sessions.update_one({"_id": ObjectId(deleted)}, {"$set": {"is_deleted": True}})
    visible = memory.create_session(7)
    _turn(7, visible, "pergunta", "resposta")

    assert [s["session_id"] for s in memory.get_sessions_for_user(7)] == [visible]
    assert memory.count_sessions_for_user(7) == 1
    assert not memory.session_belongs_to_user(7, deleted)


def test_listing_uses_generated_meta_and_falls_back_without_it(mongo_db):
    with_meta = memory.create_session(7)
    _turn(7, with_meta, "Crie uma rotina mais sustentável.", "Aqui vai uma rotina completa.")
    memory.set_session_meta(7, with_meta, "Definir rotina nova", "Rotina para diminuir 12%", "routine")
    without_meta = memory.create_session(7)
    _turn(7, without_meta, "x" * 100, "y" * 200)

    by_id = {s["session_id"]: s for s in memory.get_sessions_for_user(7)}

    assert by_id[with_meta]["title"] == "Definir rotina nova"
    assert by_id[with_meta]["preview"] == "Rotina para diminuir 12%"
    assert by_id[with_meta]["icon"] == "routine"
    assert len(by_id[without_meta]["title"]) == 40 and by_id[without_meta]["title"].endswith("…")
    assert len(by_id[without_meta]["preview"]) == 80
    assert by_id[without_meta]["icon"] == "general"


def test_session_needs_meta_until_title_is_set(mongo_db):
    session_id = memory.create_session(7)
    assert memory.session_needs_meta(7, session_id) is True

    memory.set_session_meta(7, session_id, "Título", "Prévia", "tips")

    assert memory.session_needs_meta(7, session_id) is False
    assert memory.session_needs_meta(8, session_id) is False


def test_close_then_new_message_reopens_session(mongo_db):
    session_id = memory.create_session(7)
    memory.mark_session_closed(7, session_id)
    closed = mongo_db.chat_sessions.find_one({"_id": ObjectId(session_id)})
    assert closed["is_open"] is False and closed["is_active"] is False

    memory.append_turn(session_id, 7, "human", "voltei")

    reopened = mongo_db.chat_sessions.find_one({"_id": ObjectId(session_id)})
    assert reopened["is_open"] is True and reopened["is_active"] is True


def test_mark_closed_ignores_other_user(mongo_db):
    session_id = memory.create_session(7)
    memory.mark_session_closed(8, session_id)
    assert mongo_db.chat_sessions.find_one({"_id": ObjectId(session_id)})["is_open"] is True


def test_build_context_gives_router_the_stored_history(mongo_db):
    from app.graph.context import build_context
    from app.graph.workflow import _history_from_mongo

    session_id = memory.create_session(7)
    _turn(7, session_id, "Como diminuir meu gasto?", "Reduza o tempo de banho.")

    expected = [
        {"role": "human", "content": "Como diminuir meu gasto?"},
        {"role": "assistant", "content": "Reduza o tempo de banho."},
    ]
    assert build_context(7, session_id, "e agora?")["recent_messages"] == expected
    assert _history_from_mongo(7, session_id) == expected
    assert build_context(8, session_id, "e agora?")["recent_messages"] == []
