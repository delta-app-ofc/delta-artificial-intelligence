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


def get_sessions_for_user(user_id: int) -> list[dict]:
    """Lista todas as sessões do usuário (sem as mensagens completas)."""

    collection = get_app_client()[get_settings().mongo_db_app]["conversations"]
    cursor = collection.find(
        {"user_id": user_id},
        {"_id": 0, "session_id": 1, "created_at": 1},
    )

    return list(cursor)
