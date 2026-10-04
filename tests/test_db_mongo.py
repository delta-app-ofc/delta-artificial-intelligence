"""Testes do acesso Mongo sem conexão de rede."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pymongo.errors import (
    ExecutionTimeout,
    NetworkTimeout,
    OperationFailure,
    PyMongoError,
    ServerSelectionTimeoutError,
)

from app.config import ConfigurationError, load_settings
from app.data import db_mongo
from app.tools.exceptions import (
    DatabaseConnectionError,
    DatabaseDataError,
    DatabaseQueryError,
)


class FakeCursor:
    def __init__(self, documents: list[dict]) -> None:
        self.documents = documents
        self.sort_call: tuple[str, int] | None = None
        self.closed = False

    def sort(self, field: str, direction: int) -> "FakeCursor":
        self.sort_call = (field, direction)
        return self

    def __iter__(self):
        return iter(self.documents)

    def close(self) -> None:
        self.closed = True


class FakeCollection:
    def __init__(self, documents: list[dict] | None = None, one: dict | None = None) -> None:
        self.documents = documents or []
        self.one = one
        self.error: Exception | None = None
        self.find_call: tuple[dict, dict] | None = None
        self.find_one_call: tuple[dict, dict] | None = None
        self.cursor: FakeCursor | None = None

    def find(self, query: dict, **options) -> FakeCursor:
        self.find_call = (query, options)
        if self.error:
            raise self.error
        self.cursor = FakeCursor(self.documents)
        return self.cursor

    def find_one(self, query: dict, **options) -> dict | None:
        self.find_one_call = (query, options)
        if self.error:
            raise self.error
        return self.one


class FakeDatabase:
    def __init__(self, name: str, collections: dict[str, FakeCollection] | None = None) -> None:
        self.name = name
        self.collections = collections or {}

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections.setdefault(name, FakeCollection())


class FakeClient:
    def __init__(self, uri: str, **options) -> None:
        self.uri = uri
        self.options = options
        self.databases: dict[str, FakeDatabase] = {}
        self.closed = False

    def __getitem__(self, name: str) -> FakeDatabase:
        return self.databases.setdefault(name, FakeDatabase(name))

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def mongo_settings():
    return load_settings(
        environ={
            "APP_ENV": "test",
            "MONGODB_APP_URI": "mongodb://app-host:27017",
            "MONGODB_TELEMETRY_URI": "mongodb://telemetry-host:27018",
            "MONGO_DB_APP": "delta_test_app",
            "MONGO_DB_TELEMETRY": "delta_test_telemetry",
            "DB_CONNECT_TIMEOUT_SECONDS": "5",
            "DB_QUERY_TIMEOUT_SECONDS": "12",
        },
        env_file=None,
    )


@pytest.fixture
def use_mongo_settings(monkeypatch, mongo_settings):
    db_mongo.close_clients()
    monkeypatch.setattr(db_mongo, "get_settings", lambda: mongo_settings)
    yield mongo_settings
    db_mongo.close_clients()


def _point(**changes) -> dict:
    document = {
        "user_id": 42,
        "device_id": "synthetic-device",
        "window_started_at": datetime(2026, 10, 1, tzinfo=timezone.utc),
        "window_finished_at": datetime(2026, 10, 1, 0, 5, tzinfo=timezone.utc),
        "consumption_liters": 14.5,
        "anomaly_detected": True,
        "lpm_average": 2.9,
    }
    document.update(changes)
    return document


def test_clients_use_independent_uris_databases_and_timeouts(
    monkeypatch, use_mongo_settings
):
    created: list[FakeClient] = []

    def make_client(uri: str, **options) -> FakeClient:
        client = FakeClient(uri, **options)
        created.append(client)
        return client

    monkeypatch.setattr(db_mongo, "MongoClient", make_client)

    app_database = db_mongo._app()
    telemetry_database = db_mongo._telemetry()

    assert app_database.name == "delta_test_app"
    assert telemetry_database.name == "delta_test_telemetry"
    assert [client.uri for client in created] == [
        "mongodb://app-host:27017",
        "mongodb://telemetry-host:27018",
    ]
    assert all(
        client.options
        == {
            "tz_aware": True,
            "serverSelectionTimeoutMS": 5000,
            "connectTimeoutMS": 5000,
            "socketTimeoutMS": 12000,
        }
        for client in created
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"MONGODB_APP_URI": "mongodb://app-host:70000/db"},
        {"DB_CONNECT_TIMEOUT_SECONDS": "0"},
        {"DB_QUERY_TIMEOUT_SECONDS": "invalid"},
    ],
)
def test_invalid_uri_or_timeout_fails_before_client_creation(
    monkeypatch, mongo_settings, overrides
):
    values = {
        "APP_ENV": "test",
        "MONGODB_APP_URI": mongo_settings.mongodb_app_uri,
        "MONGODB_TELEMETRY_URI": mongo_settings.mongodb_telemetry_uri,
        "MONGO_DB_APP": mongo_settings.mongo_db_app,
        "MONGO_DB_TELEMETRY": mongo_settings.mongo_db_telemetry,
        "DB_CONNECT_TIMEOUT_SECONDS": "5",
        "DB_QUERY_TIMEOUT_SECONDS": "12",
    }
    values.update(overrides)
    settings = load_settings(environ=values, env_file=None)
    monkeypatch.setattr(db_mongo, "get_settings", lambda: settings)
    created: list[str] = []
    monkeypatch.setattr(db_mongo, "MongoClient", lambda uri, **kwargs: created.append(uri))

    with pytest.raises(ConfigurationError):
        db_mongo.get_app_client()

    assert created == []


def test_clients_are_lazy_reused_and_closed_from_cache(monkeypatch, use_mongo_settings):
    created: list[FakeClient] = []

    def make_client(uri: str, **options) -> FakeClient:
        client = FakeClient(uri, **options)
        created.append(client)
        return client

    monkeypatch.setattr(db_mongo, "MongoClient", make_client)
    assert created == []

    first_app = db_mongo.get_app_client()
    first_telemetry = db_mongo.get_telemetry_client()
    assert db_mongo.get_app_client() is first_app
    assert db_mongo.get_telemetry_client() is first_telemetry

    db_mongo.close_clients()
    assert first_app.closed and first_telemetry.closed

    reopened = db_mongo.get_app_client()
    assert reopened is not first_app
    assert not reopened.closed
    assert len(created) == 3


def test_close_clients_attempts_both_and_clears_both_caches(
    monkeypatch, use_mongo_settings
):
    created: list[FakeClient] = []

    class FailingCloseClient(FakeClient):
        def close(self) -> None:
            super().close()
            raise RuntimeError("synthetic close detail")

    def make_client(uri: str, **options) -> FakeClient:
        client = FailingCloseClient(uri, **options)
        created.append(client)
        return client

    monkeypatch.setattr(db_mongo, "MongoClient", make_client)
    db_mongo.get_app_client()
    db_mongo.get_telemetry_client()

    with pytest.raises(DatabaseConnectionError) as captured:
        db_mongo.close_clients()

    assert "synthetic" not in str(captured.value)
    assert all(client.closed for client in created)
    assert db_mongo.get_app_client.cache_info().currsize == 0
    assert db_mongo.get_telemetry_client.cache_info().currsize == 0


def test_history_preserves_user_filter_order_and_converts_aware_dates(
    monkeypatch, use_mongo_settings
):
    collection = FakeCollection(documents=[_point()])
    database = FakeDatabase("delta_test_telemetry", {"consumption_summary": collection})
    monkeypatch.setattr(db_mongo, "_telemetry", lambda: database)

    result = db_mongo.get_consumption_history(42, 7)

    assert len(result) == 1
    assert result[0].user_id == 42
    assert result[0].consumption_liters == 14.5
    assert result[0].window_started_at.tzinfo is timezone.utc
    assert result[0].window_finished_at.tzinfo is timezone.utc
    assert collection.find_call is not None
    query, options = collection.find_call
    assert query["user_id"] == 42
    assert "$gte" in query["window_started_at"]
    assert options == {"max_time_ms": 12000}
    assert collection.cursor is not None
    assert collection.cursor.sort_call == ("window_started_at", db_mongo.ASCENDING)


def test_alerts_keep_user_filter_active_filter_and_descending_order(
    monkeypatch, use_mongo_settings
):
    alert = {
        "user_id": 42,
        "device_id": "synthetic-device",
        "alert_type": "fluxo_atipico",
        "triggered_at": datetime(2026, 10, 1, tzinfo=timezone.utc),
        "resolved_at": None,
        "severity": "medium",
    }
    collection = FakeCollection(documents=[alert])
    database = FakeDatabase("delta_test_app", {"alerts_history": collection})
    monkeypatch.setattr(db_mongo, "_app", lambda: database)

    result = db_mongo.get_alerts_history(42, 30, only_active=True)

    assert result[0].user_id == 42
    assert result[0].is_active
    assert collection.find_call is not None
    query, options = collection.find_call
    assert query["user_id"] == 42
    assert query["resolved_at"] is None
    assert options == {"max_time_ms": 12000}
    assert collection.cursor is not None
    assert collection.cursor.sort_call == ("triggered_at", db_mongo.DESCENDING)


def test_empty_collection_and_missing_preference_remain_legitimate_absence(
    monkeypatch, use_mongo_settings
):
    telemetry = FakeDatabase(
        "delta_test_telemetry", {"consumption_summary": FakeCollection()}
    )
    app = FakeDatabase("delta_test_app", {"user_preferences": FakeCollection(one=None)})
    monkeypatch.setattr(db_mongo, "_telemetry", lambda: telemetry)
    monkeypatch.setattr(db_mongo, "_app", lambda: app)

    assert db_mongo.get_consumption_history(42, 7) == []
    assert db_mongo.get_daily_liters_target(42) is None
    assert app["user_preferences"].find_one_call == (
        {"user_id": 42},
        {"max_time_ms": 12000},
    )


def test_invalid_required_consumption_field_is_a_safe_data_error(
    monkeypatch, use_mongo_settings
):
    collection = FakeCollection(documents=[_point(consumption_liters=None)])
    monkeypatch.setattr(
        db_mongo,
        "_telemetry",
        lambda: FakeDatabase("delta_test_telemetry", {"consumption_summary": collection}),
    )

    with pytest.raises(DatabaseQueryError) as captured:
        db_mongo.get_consumption_history(42, 7)

    assert isinstance(captured.value, DatabaseDataError)
    assert "MongoDB" in str(captured.value)
    assert "None" not in str(captured.value)
    assert collection.cursor is not None and collection.cursor.closed


def test_missing_required_device_id_is_a_safe_data_error(monkeypatch, use_mongo_settings):
    collection = FakeCollection(documents=[_point(device_id=None)])
    monkeypatch.setattr(
        db_mongo,
        "_telemetry",
        lambda: FakeDatabase("delta_test_telemetry", {"consumption_summary": collection}),
    )

    with pytest.raises(DatabaseDataError):
        db_mongo.get_consumption_history(42, 7)

    assert collection.cursor is not None and collection.cursor.closed


def test_invalid_anomaly_flag_is_not_coerced_to_true(monkeypatch, use_mongo_settings):
    collection = FakeCollection(documents=[_point(anomaly_detected="false")])
    monkeypatch.setattr(
        db_mongo,
        "_telemetry",
        lambda: FakeDatabase("delta_test_telemetry", {"consumption_summary": collection}),
    )

    with pytest.raises(DatabaseDataError):
        db_mongo.get_consumption_history(42, 7)


def test_alert_with_invalid_resolved_at_is_a_safe_data_error(
    monkeypatch, use_mongo_settings
):
    collection = FakeCollection(
        documents=[
            {
                "user_id": 42,
                "device_id": "synthetic-device",
                "alert_type": "fluxo_atipico",
                "triggered_at": datetime(2026, 10, 1, tzinfo=timezone.utc),
                "resolved_at": datetime(2026, 10, 1),
            }
        ]
    )
    monkeypatch.setattr(
        db_mongo,
        "_app",
        lambda: FakeDatabase("delta_test_app", {"alerts_history": collection}),
    )

    with pytest.raises(DatabaseDataError):
        db_mongo.get_alerts_history(42, 30)

    assert collection.cursor is not None and collection.cursor.closed


def test_invalid_query_timeout_stays_a_configuration_error(monkeypatch, mongo_settings):
    settings = load_settings(
        environ={
            "APP_ENV": "test",
            "MONGODB_APP_URI": mongo_settings.mongodb_app_uri,
            "MONGODB_TELEMETRY_URI": mongo_settings.mongodb_telemetry_uri,
            "MONGO_DB_APP": mongo_settings.mongo_db_app,
            "MONGO_DB_TELEMETRY": mongo_settings.mongo_db_telemetry,
            "DB_CONNECT_TIMEOUT_SECONDS": "5",
            "DB_QUERY_TIMEOUT_SECONDS": "0",
        },
        env_file=None,
    )
    monkeypatch.setattr(db_mongo, "get_settings", lambda: settings)
    monkeypatch.setattr(db_mongo, "_app", lambda: FakeDatabase("delta_test_app"))

    with pytest.raises(ConfigurationError):
        db_mongo.get_daily_liters_target(42)


@pytest.mark.parametrize(
    ("driver_error", "expected_error"),
    [
        (
            ServerSelectionTimeoutError(
                "mongodb://synthetic-user:synthetic-password@unavailable.invalid"
            ),
            DatabaseConnectionError,
        ),
        (NetworkTimeout("synthetic network timeout"), DatabaseConnectionError),
        (ExecutionTimeout("synthetic maxTimeMS timeout"), DatabaseQueryError),
        (OperationFailure("synthetic authentication detail", code=18), DatabaseConnectionError),
        (PyMongoError("synthetic query detail"), DatabaseQueryError),
    ],
)
def test_driver_errors_are_safe_and_never_look_like_empty_results(
    monkeypatch, use_mongo_settings, driver_error, expected_error
):
    collection = FakeCollection()
    collection.error = driver_error
    monkeypatch.setattr(
        db_mongo,
        "_telemetry",
        lambda: FakeDatabase("delta_test_telemetry", {"consumption_summary": collection}),
    )

    with pytest.raises(expected_error) as captured:
        db_mongo.get_consumption_history(42, 7)

    assert "synthetic" not in str(captured.value)
    assert "mongodb://" not in str(captured.value)
    assert "@unavailable.invalid" not in str(captured.value)
