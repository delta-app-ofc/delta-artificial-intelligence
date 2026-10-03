"""Memória de sessão em MongoDB — histórico de mensagens por conversa."""

from __future__ import annotations

from datetime import datetime, timezone

from app.data.db_mongo import get_app_client
from app.config import MONGO_DB_APP


def _col():
    return get_app_client()[MONGO_DB_APP]["conversations"]


def load_history(session_id: str) -> list[dict]:
    """Retorna todas as mensagens da sessão ordenadas por timestamp."""
    doc = _col().find_one({"session_id": session_id}, {"_id": 0, "messages": 1})
    return (doc or {}).get("messages", [])


def append_turn(session_id: str, user_id: int, role: str, content: str) -> None:
    """Anexa uma mensagem ao histórico da sessão, criando o documento se necessário."""
    _col().update_one(
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
    cursor = _col().find(
        {"user_id": user_id},
        {"_id": 0, "session_id": 1, "created_at": 1},
    )
    return list(cursor)
