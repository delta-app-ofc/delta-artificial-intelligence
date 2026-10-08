"""Testes do CLI Mongo com clientes locais em memória."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from bson import ObjectId
from pymongo.errors import ServerSelectionTimeoutError

from app.config import load_settings
from app.data import db_mongo
from scripts import check_mongo


def _settings():
    return load_settings(
        environ={
            "APP_ENV": "test",
            "MONGODB_APP_URI": "mongodb://127.0.0.1:27018",
            "MONGODB_TELEMETRY_URI": "mongodb://localhost:27018",
            "MONGO_DB_APP": "delta_test_app",
            "MONGO_DB_TELEMETRY": "delta_test_telemetry",
            "DB_QUERY_TIMEOUT_SECONDS": "9",
        },
        env_file=None,
    )


class _Admin:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def command(self, name: str) -> dict:
        assert name == "ping"
        if self.error:
            raise self.error
        return {"ok": 1}


class _Cursor:
    def __init__(self, documents: list[dict]) -> None:
        self.documents = documents

    def sort(self, field: str, direction: int) -> "_Cursor":
        self.documents.sort(key=lambda document: document[field], reverse=direction < 0)
        return self

    def __iter__(self):
        return iter(self.documents)

    def close(self) -> None:
        pass


class _Collection:
    def __init__(self, name: str, *, fail_insert: bool = False) -> None:
        self.name = name
        self.documents: dict[ObjectId, dict] = {}
        self.fail_insert = fail_insert
        self.attempted_ids: list[ObjectId] = []
        self.deleted_filters: list[dict] = []

    def find_one(self, query: dict, projection=None, **options) -> dict | None:
        for document in self.documents.values():
            if all(document.get(key) == value for key, value in query.items()):
                return document
        return None

    def insert_one(self, document: dict) -> None:
        self.attempted_ids.append(document["_id"])
        if self.fail_insert:
            raise RuntimeError("synthetic insert failure")
        self.documents[document["_id"]] = document

    def find(self, query: dict, **options) -> _Cursor:
        documents = []
        for document in self.documents.values():
            if document.get("user_id") != query.get("user_id"):
                continue
            time_filter = query.get("window_started_at", {})
            if document.get("window_started_at") < time_filter.get("$gte"):
                continue
            documents.append(document)
        return _Cursor(documents)

    def delete_one(self, query: dict) -> None:
        self.deleted_filters.append(query)
        self.documents.pop(query["_id"], None)


class _Database:
    def __init__(self, collections: dict[str, _Collection]) -> None:
        self.collections = collections

    def __getitem__(self, name: str) -> _Collection:
        return self.collections[name]


class _Client:
    def __init__(self, database: _Database, error: Exception | None = None) -> None:
        self.database = database
        self.admin = _Admin(error)

    def __getitem__(self, name: str) -> _Database:
        return self.database


def test_cli_checks_both_targets_when_one_ping_fails(monkeypatch, capfd):
    settings = _settings()
    app = _Client(
        _Database({"user_preferences": _Collection("user_preferences")}),
        ServerSelectionTimeoutError("mongodb://synthetic-secret@offline.invalid"),
    )
    telemetry = _Client(
        _Database({"consumption_summary": _Collection("consumption_summary")})
    )
    monkeypatch.setattr(check_mongo, "get_settings", lambda: settings)
    monkeypatch.setattr(
        check_mongo,
        "_client_and_database",
        lambda component: (app, settings.mongo_db_app)
        if component == "app"
        else (telemetry, settings.mongo_db_telemetry),
    )
    monkeypatch.setattr(db_mongo, "close_clients", lambda: None)

    status = check_mongo.main([])
    captured = capfd.readouterr()

    assert status != 0
    assert "MongoDB app: erro=" in captured.err
    assert "MongoDB telemetry: database=delta_test_telemetry" in captured.out
    assert "collection=consumption_summary ping=ok leitura=sem_documento" in captured.out
    assert "synthetic" not in captured.err
    assert "offline.invalid" not in captured.err


@pytest.mark.parametrize("fail_second_insert", [False, True])
def test_fixture_reads_converts_and_cleans_only_its_ids(
    monkeypatch, capfd, fail_second_insert
):
    settings = _settings()
    app_collection = _Collection("user_preferences")
    telemetry_collection = _Collection(
        "consumption_summary", fail_insert=fail_second_insert
    )
    app_sentinel_id = ObjectId()
    telemetry_sentinel_id = ObjectId()
    app_collection.documents[app_sentinel_id] = {
        "_id": app_sentinel_id,
        "user_id": 15,
        "daily_liters_target": 250,
        "dark_mode_enabled": False,
    }
    telemetry_collection.documents[telemetry_sentinel_id] = {
        "_id": telemetry_sentinel_id,
        "user_id": 15,
        "device_id": "existing-device",
        "window_started_at": datetime.now(timezone.utc),
        "window_finished_at": datetime.now(timezone.utc),
        "consumption_liters": 1.0,
        "anomaly_detected": False,
    }
    app_database = _Database({"user_preferences": app_collection})
    telemetry_database = _Database({"consumption_summary": telemetry_collection})
    app_client = _Client(app_database)
    telemetry_client = _Client(telemetry_database)

    monkeypatch.setattr(check_mongo, "get_settings", lambda: settings)
    monkeypatch.setattr(
        check_mongo,
        "_client_and_database",
        lambda component: (app_client, settings.mongo_db_app)
        if component == "app"
        else (telemetry_client, settings.mongo_db_telemetry),
    )
    monkeypatch.setattr(db_mongo, "get_settings", lambda: settings)
    monkeypatch.setattr(db_mongo, "_app", lambda: app_database)
    monkeypatch.setattr(db_mongo, "_telemetry", lambda: telemetry_database)

    if fail_second_insert:
        with pytest.raises(RuntimeError, match="synthetic insert failure"):
            check_mongo._run_fixture(settings)
    else:
        check_mongo._run_fixture(settings)
        captured = capfd.readouterr()
        assert "database=delta_test_app collection=user_preferences" in captured.out
        assert "database=delta_test_telemetry collection=consumption_summary" in captured.out
        assert "leitura=convertida" in captured.out

    assert app_collection.deleted_filters == [
        {"_id": app_collection.attempted_ids[0]}
    ]
    assert telemetry_collection.deleted_filters == [
        {"_id": telemetry_collection.attempted_ids[0]}
    ]
    assert set(app_collection.documents) == {app_sentinel_id}
    assert set(telemetry_collection.documents) == {telemetry_sentinel_id}
