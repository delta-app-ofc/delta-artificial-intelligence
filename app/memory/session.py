"""Memória de sessão em MongoDB — coleção `chat_sessions` (schema do delta-mongo-database).

O identificador público da sessão é o `_id` (ObjectId) em texto. Ele é sempre
criado pelo servidor; o cliente só devolve um id que já recebeu.
"""

from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId

from app.data.db_mongo import get_app_client
from app.config import get_settings

_ROLE_TO_DB = {"human": "user", "user": "user", "assistant": "bot", "bot": "bot"}
_CHAT_ROLES = {"user": "human", "bot": "assistant"}

_TITLE_MAX = 40
_PREVIEW_MAX = 80


def _collection():
    return get_app_client()[get_settings().mongo_db_app]["chat_sessions"]


def _object_id(session_id: str) -> ObjectId | None:
    try:
        return ObjectId(session_id)
    except (InvalidId, TypeError):
        return None


def _shorten(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def create_session(user_id: int) -> str:
    """Cria uma sessão vazia e devolve seu id."""
    now = datetime.now(timezone.utc)
    result = _collection().insert_one(
        {
            "user_id": user_id,
            "started_at": now,
            "last_activity_at": now,
            "is_open": True,
            "is_active": True,
            "is_deleted": False,
            "messages": [],
        }
    )
    return str(result.inserted_id)


def session_belongs_to_user(user_id: int, session_id: str) -> bool:
    """Indica se a sessão existe, não foi excluída e pertence a user_id."""
    object_id = _object_id(session_id)
    if object_id is None:
        return False

    return (
        _collection().count_documents(
            {"_id": object_id, "user_id": user_id, "is_deleted": {"$ne": True}},
            limit=1,
        )
        > 0
    )


def discard_empty_session(user_id: int, session_id: str) -> None:
    """Remove a sessão de user_id só se ela ainda não tiver mensagens."""
    object_id = _object_id(session_id)
    if object_id is None:
        return

    _collection().delete_one(
        {"_id": object_id, "user_id": user_id, "messages.0": {"$exists": False}}
    )


def load_history_validated(user_id: int, session_id: str) -> list[dict]:
    """Retorna o histórico somente se a sessão pertencer a user_id.

    Retorna lista vazia quando a sessão não existe ou pertence a outro usuário.
    Os papéis voltam como estão no banco: `user` ou `bot`.
    """
    object_id = _object_id(session_id)
    if object_id is None:
        return []

    doc = _collection().find_one(
        {"_id": object_id, "user_id": user_id, "is_deleted": {"$ne": True}},
        {"_id": 0, "messages": 1},
    )

    return [
        {
            "role": m.get("role"),
            "content": m.get("content", ""),
            "timestamp": m.get("sent_at"),
        }
        for m in (doc or {}).get("messages", [])
    ]


def to_chat_messages(history: list[dict]) -> list[dict]:
    """Converte o histórico do banco (`user`/`bot`) para o formato do chat (`human`/`assistant`)."""
    return [
        {"role": _CHAT_ROLES[m["role"]], "content": m["content"]}
        for m in history
        if m.get("role") in _CHAT_ROLES
    ]


def append_turn(
    session_id: str,
    user_id: int,
    role: str,
    content: str,
    api_status_code: int = 200,
) -> None:
    """Anexa uma mensagem à sessão de user_id e reabre a sessão se estava fechada.

    Levanta ValueError quando a sessão não existe ou pertence a outro usuário,
    sem diferenciar os dois casos.
    """
    db_role = _ROLE_TO_DB.get(role)
    if db_role is None:
        raise ValueError(f"papel inválido: {role!r}")

    object_id = _object_id(session_id)
    now = datetime.now(timezone.utc)
    result = None
    if object_id is not None:
        result = _collection().update_one(
            {"_id": object_id, "user_id": user_id, "is_deleted": {"$ne": True}},
            {
                "$push": {
                    "messages": {
                        "role": db_role,
                        "content_type": "text",
                        "content": content,
                        "sent_at": now,
                        "api_status_code": api_status_code,
                    }
                },
                "$set": {"last_activity_at": now, "is_open": True, "is_active": True},
            },
        )

    if result is None or result.matched_count == 0:
        raise ValueError("sessão não encontrada para este usuário")


def mark_session_closed(user_id: int, session_id: str) -> None:
    object_id = _object_id(session_id)
    if object_id is None:
        return

    _collection().update_one(
        {"_id": object_id, "user_id": user_id, "is_deleted": {"$ne": True}},
        {"$set": {"is_open": False, "is_active": False}},
    )


def session_needs_meta(user_id: int, session_id: str) -> bool:
    """Indica se a sessão ainda não tem título gerado."""
    object_id = _object_id(session_id)
    if object_id is None:
        return False

    doc = _collection().find_one(
        {"_id": object_id, "user_id": user_id, "is_deleted": {"$ne": True}}, {"_id": 0, "title": 1}
    )
    return doc is not None and not doc.get("title")


def set_session_meta(user_id: int, session_id: str, title: str, preview: str, icon: str) -> None:
    object_id = _object_id(session_id)
    if object_id is None:
        return

    _collection().update_one(
        {"_id": object_id, "user_id": user_id, "is_deleted": {"$ne": True}},
        {"$set": {"title": title, "preview": preview, "icon": icon}},
    )


def count_sessions_for_user(user_id: int) -> int:
    return _collection().count_documents(_listing_filter(user_id))


def _listing_filter(user_id: int) -> dict:
    # Sessões sem mensagens (ex.: pergunta bloqueada pelo guardrail) não aparecem.
    return {
        "user_id": user_id,
        "is_deleted": {"$ne": True},
        "messages.0": {"$exists": True},
    }


def get_sessions_for_user(user_id: int, limit: int = 20, offset: int = 0) -> list[dict]:
    """Lista as sessões do usuário, da mais recente para a mais antiga.

    Sem `title`/`preview` gravados (a geração pela LLM falhou ou ainda não
    aconteceu), usa o início da primeira pergunta e o fim da última mensagem.
    """
    pipeline = [
        {"$match": _listing_filter(user_id)},
        {"$sort": {"last_activity_at": -1}},
        {"$skip": offset},
        {"$limit": limit},
        {
            "$project": {
                "title": 1,
                "preview": 1,
                "icon": 1,
                "started_at": 1,
                "last_activity_at": 1,
                "is_open": 1,
                "first_message": {"$arrayElemAt": ["$messages", 0]},
                "last_message": {"$arrayElemAt": ["$messages", -1]},
            }
        },
    ]

    sessions = []
    for doc in _collection().aggregate(pipeline):
        sessions.append(
            {
                "session_id": str(doc["_id"]),
                "title": doc.get("title")
                or _shorten((doc.get("first_message") or {}).get("content", ""), _TITLE_MAX),
                "preview": doc.get("preview")
                or _shorten((doc.get("last_message") or {}).get("content", ""), _PREVIEW_MAX),
                "icon": doc.get("icon") or "general",
                "created_at": doc.get("started_at"),
                "updated_at": doc.get("last_activity_at"),
                "is_open": bool(doc.get("is_open", False)),
            }
        )

    return sessions
