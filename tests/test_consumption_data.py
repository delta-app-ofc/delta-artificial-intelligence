"""Verifica filtros e parâmetros dos leitores de consumo por período."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.data import db_mongo, db_postgres

UTC = timezone.utc


def test_mongo_range_reader_binds_user_and_utc_half_open_finished_window(monkeypatch):
    captured = {}

    def fake_read_many(*args):
        captured["args"] = args
        return ["point"]

    monkeypatch.setattr(db_mongo, "_read_many", fake_read_many)
    result = db_mongo.get_consumption_history_between(
        41,
        datetime(2026, 9, 1, 0, tzinfo=timezone(timedelta(hours=-3))),
        datetime(2026, 9, 2, 0, tzinfo=timezone(timedelta(hours=-3))),
        datetime(2026, 9, 1, 12, tzinfo=timezone(timedelta(hours=-3))),
    )

    component, collection, query, sort_field, direction, converter = captured["args"]
    assert result == ["point"]
    assert component == "telemetry"
    assert collection == "consumption_summary"
    assert query == {
        "user_id": 41,
        "window_started_at": {
            "$gte": datetime(2026, 9, 1, 3, tzinfo=UTC),
            "$lt": datetime(2026, 9, 2, 3, tzinfo=UTC),
        },
        "window_finished_at": {"$lte": datetime(2026, 9, 1, 15, tzinfo=UTC)},
    }
    assert sort_field == "window_started_at"
    assert direction == db_mongo.ASCENDING
    assert converter is db_mongo._to_point


@pytest.mark.parametrize(
    "bounds",
    [
        (datetime(2026, 9, 1), datetime(2026, 9, 2, tzinfo=UTC), datetime(2026, 9, 2, tzinfo=UTC)),
        (datetime(2026, 9, 2, tzinfo=UTC), datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 2, tzinfo=UTC)),
    ],
)
def test_mongo_range_reader_rejects_naive_or_inverted_bounds_before_read(monkeypatch, bounds):
    called = False

    def fail_if_read(*args):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(db_mongo, "_read_many", fail_if_read)
    with pytest.raises(ValueError):
        db_mongo.get_consumption_history_between(41, *bounds)
    assert called is False


def test_organization_sql_reader_binds_only_authorized_ids_and_local_dates(monkeypatch):
    class FakeCursor:
        statement = ""
        parameters = None

        def execute(self, statement, parameters):
            self.statement = statement
            self.parameters = parameters

        def fetchall(self):
            return [
                (date(2026, 9, 1), Decimal("150.000")),
                (date(2026, 9, 1), Decimal("200.000")),
            ]

    cursor = FakeCursor()

    @contextmanager
    def fake_cursor():
        yield cursor

    monkeypatch.setattr(db_postgres, "_cursor", fake_cursor)
    start = date(2026, 9, 1)
    end = date(2026, 9, 3)
    records = db_postgres.get_organization_consumption_daily([151, 152], start, end)

    assert records == [
        (date(2026, 9, 1), Decimal("150.000")),
        (date(2026, 9, 1), Decimal("200.000")),
    ]
    assert "property_id = ANY(%s)" in cursor.statement
    assert "full_date BETWEEN %s AND %s" in cursor.statement
    assert "SELECT full_date, total_liters" in cursor.statement
    assert "ORDER BY full_date, property_id" in cursor.statement
    assert cursor.parameters == ([151, 152], start, end)


def test_organization_sql_reader_does_not_query_empty_or_invalid_ranges(monkeypatch):
    called = False

    @contextmanager
    def fail_if_query():
        nonlocal called
        called = True
        yield None

    monkeypatch.setattr(db_postgres, "_cursor", fail_if_query)
    assert db_postgres.get_organization_consumption_daily([], date(2026, 9, 1), date(2026, 9, 2)) == []
    with pytest.raises(ValueError):
        db_postgres.get_organization_consumption_daily(
            [151], date(2026, 9, 2), date(2026, 9, 1)
        )
    with pytest.raises(ValueError):
        db_postgres.get_organization_consumption_daily(
            [151], datetime(2026, 9, 1), date(2026, 9, 2)
        )
    assert called is False
