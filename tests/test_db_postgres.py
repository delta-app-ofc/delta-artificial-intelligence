from __future__ import annotations

from datetime import date
from decimal import Decimal

import psycopg2
import pytest

from app.config import ConfigurationError, load_settings
from app.data import db_postgres
from app.tools.exceptions import (
    DatabaseConnectionError,
    DatabaseQueryError,
    RegionRateNotFound,
)
from app.tools.models import LastWaterBill
from scripts import check_postgres

TEST_DSN = (
    "postgresql://delta_test:synthetic%40password@db.example:5432/delta_test"
    "?sslmode=verify-full&options=-c%20search_path%3Dgold"
)
SYNTHETIC_SECRET = "synthetic-password-value"


class UndefinedTableWithCode(psycopg2.errors.UndefinedTable):
    @property
    def pgcode(self) -> str:
        return "42P01"


class FakeCursor:
    def __init__(self, *, row=None, rows=None, execute_error=None, close_error=None):
        self.row = row
        self.rows = rows or []
        self.execute_error = execute_error
        self.close_error = close_error
        self.executions: list[tuple[str, tuple | None]] = []
        self.closed = False

    def execute(self, query: str, parameters: tuple | None = None) -> None:
        self.executions.append((query, parameters))
        if self.execute_error is not None:
            raise self.execute_error

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows

    def close(self) -> None:
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


class FakeConnection:
    def __init__(self, cursor: FakeCursor | None = None, cursor_error=None):
        self.fake_cursor = cursor or FakeCursor()
        self.cursor_error = cursor_error
        self.closed = False

    def cursor(self):
        if self.cursor_error is not None:
            raise self.cursor_error
        return self.fake_cursor

    def close(self) -> None:
        self.closed = True


def _install_url_connection(monkeypatch, connection, *, dsn: str = TEST_DSN):
    settings = load_settings(
        {
            "APP_ENV": "test",
            "DATABASE_URL": dsn,
            "DB_CONNECT_TIMEOUT_SECONDS": "3",
            "DB_QUERY_TIMEOUT_SECONDS": "7",
        },
        env_file=None,
    )
    monkeypatch.setattr(db_postgres, "get_settings", lambda: settings)
    return settings


def test_get_conn_preserves_url_tls_options_and_applies_timeouts(monkeypatch):
    connection = FakeConnection()
    captured: dict = {}
    _install_url_connection(monkeypatch, connection)

    def connect(**kwargs):
        captured.update(kwargs)
        return connection

    monkeypatch.setattr(db_postgres.psycopg2, "connect", connect)

    assert db_postgres.get_conn() is connection
    assert captured["dsn"] == TEST_DSN
    assert captured["connect_timeout"] == 3
    assert captured["options"] == "-c search_path=gold -c statement_timeout=7000ms"
    assert psycopg2.extensions.parse_dsn(captured["dsn"])["sslmode"] == "verify-full"


def test_get_conn_passes_separate_variables_from_settings_helper(monkeypatch):
    connection = FakeConnection()
    captured: dict = {}
    settings = load_settings(
        {
            "APP_ENV": "test",
            "DATABASE_URL": TEST_DSN,
            "HOST_DB": "localhost",
            "PORT_DB": "5432",
            "USER_DB": "delta_test",
            "PASSWORD_DB": SYNTHETIC_SECRET,
            "NAME_DB": "delta_test",
            "DB_CONNECT_TIMEOUT_SECONDS": "4",
            "DB_QUERY_TIMEOUT_SECONDS": "2",
        },
        env_file=None,
    )
    monkeypatch.setattr(db_postgres, "get_settings", lambda: settings)
    monkeypatch.setattr(
        db_postgres.psycopg2,
        "connect",
        lambda **kwargs: captured.update(kwargs) or connection,
    )

    assert db_postgres.get_conn() is connection
    assert captured["host"] == "localhost"
    assert captured["port"] == 5432
    assert captured["password"] == SYNTHETIC_SECRET
    assert captured["connect_timeout"] == 4
    assert captured["options"] == "-c statement_timeout=2000ms"


def test_database_error_messages_use_only_known_database_names():
    query_error = DatabaseQueryError("PostgreSQL", code="42P01")
    assert str(DatabaseConnectionError("PostgreSQL")) == (
        "Não foi possível conectar ao PostgreSQL."
    )
    assert str(query_error) == "Não foi possível executar a consulta no PostgreSQL."
    assert query_error.code == "42P01"
    assert "42P01" not in str(query_error)

    with pytest.raises(ValueError) as captured:
        DatabaseQueryError(SYNTHETIC_SECRET)
    assert SYNTHETIC_SECRET not in str(captured.value)


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        ({"APP_ENV": "test", "HOST_DB": "localhost"}, "incompleta"),
        (
            {
                "APP_ENV": "test",
                "HOST_DB": "localhost",
                "PORT_DB": "70000",
                "USER_DB": "delta_test",
                "PASSWORD_DB": SYNTHETIC_SECRET,
                "NAME_DB": "delta_test",
            },
            "PORT_DB",
        ),
    ],
    ids=["partial-split", "invalid-port"],
)
def test_invalid_postgres_settings_fail_before_driver(monkeypatch, environment, message):
    settings = load_settings(environment, env_file=None)
    monkeypatch.setattr(db_postgres, "get_settings", lambda: settings)
    monkeypatch.setattr(
        db_postgres.psycopg2,
        "connect",
        lambda **kwargs: pytest.fail("driver chamado"),
    )
    with pytest.raises(ConfigurationError, match=message):
        db_postgres.get_conn()


def test_check_connection_executes_select_one_and_closes_resources(monkeypatch):
    cursor = FakeCursor(row=(1,))
    connection = FakeConnection(cursor)
    _install_url_connection(monkeypatch, connection)
    monkeypatch.setattr(db_postgres.psycopg2, "connect", lambda **kwargs: connection)

    db_postgres.check_connection()

    assert cursor.executions == [("SELECT 1;", None)]
    assert cursor.closed is True
    assert connection.closed is True


def test_check_connection_rejects_unexpected_result_and_closes_resources(monkeypatch):
    cursor = FakeCursor(row=None)
    connection = FakeConnection(cursor)
    _install_url_connection(monkeypatch, connection)
    monkeypatch.setattr(db_postgres.psycopg2, "connect", lambda **kwargs: connection)

    with pytest.raises(DatabaseQueryError, match="PostgreSQL"):
        db_postgres.check_connection()

    assert cursor.closed is True
    assert connection.closed is True


def test_connection_failure_has_safe_public_message(monkeypatch):
    _install_url_connection(monkeypatch, FakeConnection())

    def fail_connect(**kwargs):
        raise psycopg2.OperationalError(f"password={SYNTHETIC_SECRET}; dsn={TEST_DSN}")

    monkeypatch.setattr(db_postgres.psycopg2, "connect", fail_connect)

    with pytest.raises(DatabaseConnectionError) as captured:
        db_postgres.get_conn()

    assert SYNTHETIC_SECRET not in str(captured.value)
    assert TEST_DSN not in str(captured.value)
    assert SYNTHETIC_SECRET in str(captured.value.__cause__)


def test_cursor_failure_closes_connection_and_is_safe(monkeypatch):
    connection = FakeConnection(
        cursor_error=psycopg2.InterfaceError(f"password={SYNTHETIC_SECRET}")
    )
    _install_url_connection(monkeypatch, connection)
    monkeypatch.setattr(db_postgres.psycopg2, "connect", lambda **kwargs: connection)

    with pytest.raises(DatabaseQueryError) as captured:
        db_postgres.check_connection()

    assert connection.closed is True
    assert SYNTHETIC_SECRET not in str(captured.value)


def test_query_error_is_distinct_from_no_rows_and_closes_resources(monkeypatch):
    cursor = FakeCursor(
        execute_error=UndefinedTableWithCode(f"table missing {SYNTHETIC_SECRET}")
    )
    connection = FakeConnection(cursor)
    _install_url_connection(monkeypatch, connection)
    monkeypatch.setattr(db_postgres.psycopg2, "connect", lambda **kwargs: connection)

    with pytest.raises(DatabaseQueryError) as captured:
        db_postgres.get_user_region_id(42)

    assert captured.value.code == "42P01"
    assert SYNTHETIC_SECRET not in str(captured.value)
    assert cursor.closed is True
    assert connection.closed is True


def test_existing_query_keeps_parameters_types_and_empty_result(monkeypatch):
    cursor = FakeCursor(row=(17,))
    connection = FakeConnection(cursor)
    _install_url_connection(monkeypatch, connection)
    monkeypatch.setattr(db_postgres.psycopg2, "connect", lambda **kwargs: connection)

    assert db_postgres.get_user_region_id(42) == 17
    query, parameters = cursor.executions[0]
    assert "WHERE up.user_id = %s" in query
    assert parameters == (42,)
    assert isinstance(parameters, tuple)

    empty_cursor = FakeCursor(row=None)
    empty_connection = FakeConnection(empty_cursor)
    _install_url_connection(monkeypatch, empty_connection)
    monkeypatch.setattr(db_postgres.psycopg2, "connect", lambda **kwargs: empty_connection)
    assert db_postgres.get_user_region_id(999) is None
    assert empty_cursor.closed is True
    assert empty_connection.closed is True


def test_existing_bill_query_keeps_dataclass_and_decimal_values(monkeypatch):
    cursor = FakeCursor(row=(9, date(2026, 8, 1), Decimal("45.70"), Decimal("8.00")))
    connection = FakeConnection(cursor)
    _install_url_connection(monkeypatch, connection)
    monkeypatch.setattr(db_postgres.psycopg2, "connect", lambda **kwargs: connection)

    bill = db_postgres.get_last_water_bill(9)

    assert isinstance(bill, LastWaterBill)
    assert bill.user_id == 9
    assert bill.total_value == Decimal("45.70")
    assert bill.m3_value == Decimal("8.00")
    assert cursor.executions[0][1] == (9,)
    assert cursor.closed is True
    assert connection.closed is True


def test_region_rate_domain_error_remains_distinct(monkeypatch):
    cursor = FakeCursor(
        execute_error=psycopg2.errors.RaiseException(f"secret detail {SYNTHETIC_SECRET}")
    )
    connection = FakeConnection(cursor)
    _install_url_connection(monkeypatch, connection)
    monkeypatch.setattr(db_postgres.psycopg2, "connect", lambda **kwargs: connection)

    with pytest.raises(RegionRateNotFound) as captured:
        db_postgres.get_current_region_rate(1, 2, date(2026, 10, 3))

    assert SYNTHETIC_SECRET not in str(captured.value)
    assert cursor.closed is True
    assert connection.closed is True


def test_cursor_close_failure_still_closes_connection(monkeypatch):
    cursor = FakeCursor(row=(1,), close_error=psycopg2.InterfaceError("close failed"))
    connection = FakeConnection(cursor)
    _install_url_connection(monkeypatch, connection)
    monkeypatch.setattr(db_postgres.psycopg2, "connect", lambda **kwargs: connection)

    with pytest.raises(DatabaseQueryError):
        db_postgres.check_connection()

    assert cursor.closed is True
    assert connection.closed is True


def test_check_script_reports_success_without_loading_llm_settings(monkeypatch, capsys):
    monkeypatch.setattr(check_postgres.db_postgres, "check_connection", lambda: None)

    assert check_postgres.main() == 0
    assert capsys.readouterr().out == "PostgreSQL disponível: SELECT 1 retornou 1.\n"


def test_check_script_reports_only_safe_connection_error(monkeypatch, capsys):
    monkeypatch.setattr(
        check_postgres.db_postgres,
        "check_connection",
        lambda: (_ for _ in ()).throw(DatabaseConnectionError("PostgreSQL")),
    )

    assert check_postgres.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Não foi possível conectar ao PostgreSQL." in captured.err
    assert SYNTHETIC_SECRET not in captured.err
