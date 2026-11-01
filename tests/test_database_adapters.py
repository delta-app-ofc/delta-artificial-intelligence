import threading
from datetime import datetime, timezone
from types import SimpleNamespace

import psycopg2
import pytest

from app.data import db_mongo, db_postgres
from app.tools.exceptions import (
    DatabaseConnectionError,
    DatabaseDataError,
    DatabaseQueryError,
)


class FakeCursor:
    def __init__(self, *, execute_error=None, query_error=None):
        self.execute_error = execute_error
        self.query_error = query_error
        self.executed = []
        self.closed = False

    def execute(self, query, params=None):
        self.executed.append((query, params))
        if self.execute_error:
            raise self.execute_error
        if self.query_error and "set_config" not in query:
            raise self.query_error

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, cursor):
        self.fake_cursor = cursor
        self.commits = 0
        self.closed = False

    def cursor(self):
        return self.fake_cursor

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True


class FakePool:
    """Pool mínimo: entrega sempre a mesma conexão e registra como ela foi devolvida."""

    def __init__(self, connection):
        self.connection = connection
        self.returned = []

    def getconn(self):
        return self.connection

    def putconn(self, connection, close=False):
        self.returned.append((connection, close))


def use_pool(monkeypatch, connection):
    pool = FakePool(connection)
    monkeypatch.setattr(db_postgres, "_get_pool", lambda: (pool, threading.BoundedSemaphore(1)))
    monkeypatch.setattr(
        db_postgres,
        "get_settings",
        lambda: SimpleNamespace(db_query_timeout_seconds=7, db_pool_wait_seconds=1),
    )
    return pool


def test_postgres_cursor_sets_scoped_timeout_and_returns_connection_after_commit(monkeypatch):
    cursor = FakeCursor()
    connection = FakeConnection(cursor)
    pool = use_pool(monkeypatch, connection)

    with db_postgres._cursor() as active_cursor:
        assert active_cursor is cursor
        cursor.execute("SELECT 1;")

    assert cursor.executed[0] == (
        "SELECT set_config('statement_timeout', %s, true);",
        ("7000ms",),
    )
    assert connection.commits == 1
    assert cursor.closed is True
    # a conexão volta ao pool aberta, pronta para a próxima operação
    assert pool.returned == [(connection, False)]
    assert connection.closed is False


def test_postgres_query_error_is_sanitized_and_does_not_commit(monkeypatch):
    cursor = FakeCursor(query_error=psycopg2.OperationalError("secret host details"))
    connection = FakeConnection(cursor)
    pool = use_pool(monkeypatch, connection)

    with pytest.raises(DatabaseQueryError) as caught:
        with db_postgres._cursor() as active_cursor:
            active_cursor.execute("SELECT 1;")

    assert "secret host details" not in str(caught.value)
    assert connection.commits == 0
    assert cursor.closed is True
    assert pool.returned == [(connection, False)]  # conexão saudável: volta ao pool


def test_postgres_broken_connection_is_sanitized_and_discarded(monkeypatch):
    """Erro já ao preparar a conexão (set_config) indica conexão quebrada: vira erro de conexão."""
    cursor = FakeCursor(execute_error=psycopg2.OperationalError("secret host details"))
    connection = FakeConnection(cursor)
    pool = use_pool(monkeypatch, connection)

    with pytest.raises(DatabaseConnectionError) as caught:
        with db_postgres._cursor():
            pass

    assert "secret host details" not in str(caught.value)
    assert connection.commits == 0
    assert all(close is True for _, close in pool.returned)  # todas as tentativas foram descartadas


class FakeMongoCursor:
    def __init__(self, documents):
        self.documents = documents
        self.sort_args = None
        self.closed = False

    def sort(self, field, direction):
        self.sort_args = (field, direction)
        return self

    def __iter__(self):
        return iter(self.documents)

    def close(self):
        self.closed = True


class FakeMongoCollection:
    def __init__(self, cursor):
        self.cursor = cursor
        self.find_args = None

    def find(self, query, *, max_time_ms):
        self.find_args = (query, max_time_ms)
        return self.cursor


class FakeMongoDatabase:
    def __init__(self, collection):
        self.collection = collection

    def __getitem__(self, name):
        assert name == "consumption_summary"
        return self.collection


class FakeMongoClient:
    def __init__(self, database):
        self.database = database

    def __getitem__(self, name):
        assert name == "telemetry-db"
        return self.database


def _patch_mongo(monkeypatch, collection):
    settings = SimpleNamespace(
        db_query_timeout_seconds=9,
        mongo_db_telemetry="telemetry-db",
    )
    monkeypatch.setattr(db_mongo, "get_settings", lambda: settings)
    monkeypatch.setattr(
        db_mongo, "validate_mongo_config", lambda component, settings=None: None
    )
    monkeypatch.setattr(
        db_mongo,
        "get_telemetry_client",
        lambda: FakeMongoClient(FakeMongoDatabase(collection)),
    )


def _document(*, user_id=12):
    started = datetime(2026, 4, 1, 10, tzinfo=timezone.utc)
    return {
        "user_id": user_id,
        "window_started_at": started,
        "window_finished_at": datetime(2026, 4, 1, 10, 5, tzinfo=timezone.utc),
        "consumption_liters": 4.5,
        "anomaly_detected": False,
        "lpm_average": 0.9,
        "device_id": "meter-1",
    }


def test_mongo_history_uses_utc_half_open_bounds_and_closes_cursor(monkeypatch):
    cursor = FakeMongoCursor([_document()])
    collection = FakeMongoCollection(cursor)
    _patch_mongo(monkeypatch, collection)
    start = datetime(2026, 4, 1, 10, tzinfo=timezone.utc)
    end = datetime(2026, 4, 2, 10, tzinfo=timezone.utc)
    finished_before = datetime(2026, 4, 2, 11, tzinfo=timezone.utc)

    points = db_mongo.get_consumption_history_between(
        12, start, end, finished_before
    )

    query, max_time_ms = collection.find_args
    assert query == {
        "user_id": 12,
        "window_started_at": {"$gte": start, "$lt": end},
        "window_finished_at": {"$lte": finished_before},
    }
    assert max_time_ms == 9000
    assert cursor.sort_args == ("window_started_at", db_mongo.ASCENDING)
    assert cursor.closed is True
    assert points[0].consumption_liters == 4.5
    assert points[0].device_id == "meter-1"


def test_mongo_malformed_document_becomes_safe_data_error_and_closes_cursor(monkeypatch):
    cursor = FakeMongoCursor([{"user_id": "not-an-integer"}])
    collection = FakeMongoCollection(cursor)
    _patch_mongo(monkeypatch, collection)
    now = datetime(2026, 4, 1, tzinfo=timezone.utc)

    with pytest.raises(DatabaseDataError):
        db_mongo.get_consumption_history_between(
            12, now, datetime(2026, 4, 2, tzinfo=timezone.utc), now
        )

    assert cursor.closed is True


def test_mongo_history_rejects_naive_or_reversed_query_bounds_before_access():
    aware = datetime(2026, 4, 1, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="fuso horário"):
        db_mongo.get_consumption_history_between(
            12, aware.replace(tzinfo=None), aware, aware
        )
    with pytest.raises(ValueError, match="anterior"):
        db_mongo.get_consumption_history_between(
            12, aware, aware, aware
        )


def test_mongo_authentication_failure_maps_to_connection_error():
    from pymongo.errors import OperationFailure

    with pytest.raises(DatabaseConnectionError):
        db_mongo._run_query(lambda: (_ for _ in ()).throw(OperationFailure("denied", code=13)))
