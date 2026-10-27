"""Memória de sessão em MongoDB — histórico de mensagens por conversa."""

from __future__ import annotations

import warnings
from datetime import datetime, timezone

from app.data.db_mongo import get_app_client
from app.config import get_settings


def load_history(session_id: str) -> list[dict]:
    """DESCONTINUADA: não valida o dono da sessão. Use load_history_validated."""
    warnings.warn(
        "load_history não valida o dono da sessão; use load_history_validated.",
        DeprecationWarning,
        stacklevel=2,
    )

    collection = get_app_client()[get_settings().mongo_db_app]["conversations"]
    doc = collection.find_one({"session_id": session_id}, {"_id": 0, "messages": 1})

    return (doc or {}).get("messages", [])


def load_history_validated(user_id: int, session_id: str) -> list[dict]:
    """Retorna o histórico somente se a sessão pertencer a user_id.

    Silenciosamente retorna lista vazia quando a sessão não existe ou pertence
    a outro usuário — sem expor a existência da sessão a quem não tem acesso.
    """
    collection = get_app_client()[get_settings().mongo_db_app]["conversations"]
    doc = collection.find_one(
        {"session_id": session_id},
        {"_id": 0, "user_id": 1, "messages": 1},
    )
    if doc is None or doc.get("user_id") != user_id:
        return []

    return doc.get("messages", [])


def append_turn(session_id: str, user_id: int, role: str, content: str) -> None:
    """Anexa uma mensagem ao histórico da sessão, criando o documento se necessário.

    Rejeita sessões que já existam e pertençam a outro usuário, evitando que
    uma colisão de session_id grave mensagens na sessão alheia.
    """
    collection = get_app_client()[get_settings().mongo_db_app]["conversations"]
    existing = collection.find_one({"session_id": session_id}, {"user_id": 1})

    if existing and existing.get("user_id") != user_id:
        raise ValueError(f"session {session_id!r} pertence a outro usuário")

    collection.update_one(
        {"session_id": session_id},
        {
            "$setOnInsert": {"user_id": user_id, "created_at": datetime.now(timezone.utc)},
            "$push": {
                "messages": {
                    "role": role,
                    "content": content,
                    "timestamp": datetime.now(timezone.utc),
                }
            },
        },
        upsert=True,
    )


_TITLE_MAX = 40
_PREVIEW_MAX = 80


def _shorten(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def count_sessions_for_user(user_id: int) -> int:
    collection = get_app_client()[get_settings().mongo_db_app]["conversations"]
    return collection.count_documents({"user_id": user_id})


def get_sessions_for_user(user_id: int, limit: int = 20, offset: int = 0) -> list[dict]:
    """Lista as sessões do usuário, da mais recente para a mais antiga.

    Cada item traz título (início da primeira pergunta), prévia (fim da última
    resposta) e a data da última mensagem, sem devolver o histórico completo.
    """

    collection = get_app_client()[get_settings().mongo_db_app]["conversations"]
    pipeline = [
        {"$match": {"user_id": user_id}},
        {
            "$project": {
                "_id": 0,
                "session_id": 1,
                "created_at": 1,
                "first_human": {
                    "$arrayElemAt": [
                        {"$filter": {"input": {"$ifNull": ["$messages", []]}, "cond": {"$eq": ["$$this.role", "human"]}}},
                        0,
                    ]
                },
                "last_assistant": {
                    "$arrayElemAt": [
                        {"$filter": {"input": {"$ifNull": ["$messages", []]}, "cond": {"$eq": ["$$this.role", "assistant"]}}},
                        -1,
                    ]
                },
                "last_message": {"$arrayElemAt": [{"$ifNull": ["$messages", []]}, -1]},
            }
        },
        {"$addFields": {"updated_at": {"$ifNull": ["$last_message.timestamp", "$created_at"]}}},
        {"$sort": {"updated_at": -1}},
        {"$skip": offset},
        {"$limit": limit},
    ]

    sessions = []
    for doc in collection.aggregate(pipeline):
        sessions.append(
            {
                "session_id": doc["session_id"],
                "title": _shorten((doc.get("first_human") or {}).get("content", ""), _TITLE_MAX),
                "preview": _shorten((doc.get("last_assistant") or {}).get("content", ""), _PREVIEW_MAX),
                "created_at": doc.get("created_at"),
                "updated_at": doc.get("updated_at"),
            }
        )

    return sessions
