"""Fixtures dos testes de histórico: MongoDB real, em um banco descartável.

Os testes usam `delta_test_historico` (prefixo `delta_test_`) e o apagam ao final.
Sem MongoDB acessível, são pulados. A URI vem de DELTA_TEST_MONGO_URI e, por padrão,
aponta para o container de docker-compose.dev.yml (localhost:27018).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from pymongo import MongoClient
from pymongo.errors import PyMongoError

TEST_MONGO_URI = os.environ.get("DELTA_TEST_MONGO_URI", "mongodb://localhost:27018")
TEST_DB = "delta_test_historico"
JWT_SECRET = "segredo-de-teste-com-mais-de-32-caracteres"

# Cópia do validador de scripts/delta-app/script-collections.js (delta-mongo-database).
CHAT_SESSIONS_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["user_id", "started_at"],
        "properties": {
            "_id": {"bsonType": "objectId"},
            "user_id": {"bsonType": "int"},
            "started_at": {"bsonType": "date"},
            "last_activity_at": {"bsonType": "date"},
            "is_open": {"bsonType": "bool"},
            "is_active": {"bsonType": "bool"},
            "is_deleted": {"bsonType": "bool"},
            "messages": {
                "bsonType": "array",
                "items": {
                    "bsonType": "object",
                    "required": ["role", "content_type", "content", "api_status_code"],
                    "properties": {
                        "role": {"enum": ["user", "bot"]},
                        "content_type": {"bsonType": "string", "enum": ["text", "function"]},
                        "content": {"bsonType": "string"},
                        "sent_at": {"bsonType": "date"},
                        "api_status_code": {"bsonType": "int"},
                    },
                },
            },
        },
    }
}


@pytest.fixture
def mongo_db(monkeypatch):
    client = MongoClient(TEST_MONGO_URI, serverSelectionTimeoutMS=2000)
    try:
        client.admin.command("ping")
    except PyMongoError:
        client.close()
        pytest.skip("MongoDB de teste indisponível (defina DELTA_TEST_MONGO_URI).")

    client.drop_database(TEST_DB)
    db = client[TEST_DB]
    db.create_collection(
        "chat_sessions", validator=CHAT_SESSIONS_VALIDATOR, validationLevel="moderate"
    )
    db.chat_sessions.create_index([("user_id", 1), ("last_activity_at", -1)])
    db.chat_sessions.create_index([("user_id", 1), ("is_open", 1)])

    monkeypatch.setattr("app.memory.session.get_app_client", lambda: client)
    monkeypatch.setattr(
        "app.memory.session.get_settings", lambda: SimpleNamespace(mongo_db_app=TEST_DB)
    )

    yield db

    client.drop_database(TEST_DB)
    client.close()


def auth_settings(**overrides):
    """Settings de autenticação para os testes: HS256 de teste, sem consultar o banco."""
    base = dict(
        jwt_secret=None, auth_public_key=None, auth_issuer="delta-api", auth_audience="delta-api",
        auth_key_id="delta-1", auth_check_active=False, app_env="test",
    )
    return SimpleNamespace(**{**base, **overrides})


def make_token(user_id, *, secret: str = JWT_SECRET, expires_in: int = 3600, **extra) -> str:
    claims = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(seconds=expires_in),
    }
    claims.update(extra)
    return jwt.encode(claims, secret, algorithm="HS256")


def auth_header(user_id: int) -> dict:
    return {"Authorization": f"Bearer {make_token(user_id)}"}
