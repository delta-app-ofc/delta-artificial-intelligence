"""Testes das tools de consumo com leitores controlados e escopo autorizado."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.data import db_mongo, db_postgres
from app.tools.exceptions import DatabaseDataError, DatabaseQueryError
from app.tools.models import ConsumptionPoint, OrganizationProperty
from app.tools.consumption.tools import build_tools

UTC = timezone.utc
NOW = datetime(2026, 9, 4, 12, tzinfo=UTC)


def _point(start: datetime, liters: float, *, device_id: str = "device-a") -> ConsumptionPoint:
    return ConsumptionPoint(
        user_id=11,
        window_started_at=start,
        window_finished_at=start + timedelta(minutes=5),
        consumption_liters=liters,
        anomaly_detected=False,
        lpm_average=1.0,
        device_id=device_id,
    )


def _toolset(monkeypatch, *, access="residential", properties=(), clock=None):
    monkeypatch.setattr(db_postgres, "get_user_access_kind", lambda user_id: access)
    monkeypatch.setattr(
        db_postgres,
        "get_user_organization_properties",
        lambda user_id: list(properties),
    )
    tools = build_tools(11, clock=clock or (lambda: NOW))
    return {item.name: item for item in tools}


def test_residential_summary_binds_user_and_does_not_accept_user_id(monkeypatch):
    captured = {}

    def fake_history(user_id, start_utc, end_utc, finished_before):
        captured.update(
            user_id=user_id,
            start=start_utc,
            end=end_utc,
            finished_before=finished_before,
        )
        return [
            _point(datetime(2026, 9, 1, 12, tzinfo=UTC), 100),
            _point(datetime(2026, 9, 1, 12, tzinfo=UTC), 50, device_id="device-b"),
            _point(datetime(2026, 9, 2, 12, tzinfo=UTC), 200),
        ]

    monkeypatch.setattr(db_mongo, "get_consumption_history_between", fake_history)
    tools = _toolset(monkeypatch)
    tool = tools["get_consumption_summary"]

    result = tool.invoke(
        {
            "period": "custom",
            "start_date": "2026-09-01",
            "end_date": "2026-09-03",
        }
    )

    assert "user_id" not in tool.args_schema.model_fields
    assert set(captured) == {"user_id", "start", "end", "finished_before"}
    assert captured["user_id"] == 11
    assert captured["start"] == datetime(2026, 9, 1, 3, tzinfo=UTC)
    assert captured["end"] == datetime(2026, 9, 4, 3, tzinfo=UTC)
    assert captured["finished_before"] == NOW
    assert result["status"] == "ok"
    assert result["source"] == "MongoDB consumption_summary"
    assert result["metrics"]["total_liters"] == 350
    assert result["metrics"]["days_with_records"] == 2
    assert result["metrics"]["average_liters_per_recorded_day"] == 175
    assert result["daily_consumption"] == [
        {"date": "2026-09-01", "liters": 150},
        {"date": "2026-09-02", "liters": 200},
    ]
    quality = result["data_quality"]
    assert quality["dates_without_records"] == ["2026-09-03"]
    assert quality["partial_data"] is True
    assert quality["coverage"] == "não determinada"


def test_residential_scope_has_priority_and_does_not_fake_property_mapping(monkeypatch):
    queried = False

    def fail_if_queried(*args):
        nonlocal queried
        queried = True
        return []

    monkeypatch.setattr(db_mongo, "get_consumption_history_between", fail_if_queried)
    tools = _toolset(
        monkeypatch,
        access="residential",
        properties=[OrganizationProperty(151, "unidade", "Sao Paulo", "SP")],
    )
    result = tools["get_consumption_summary"].invoke(
        {
            "period": "last_7_days",
            "unit_id": 151,
        }
    )

    assert result["status"] == "insufficient_data"
    assert "não associa" in result["message"]
    assert queried is False


def test_organization_selection_requires_authorized_id_and_resolves_exact_name_first(monkeypatch):
    properties = [
        OrganizationProperty(151, "Campus", "Sao Paulo", "SP"),
        OrganizationProperty(152, "Campus", "Campinas", "SP"),
        OrganizationProperty(153, "Campus Norte", "Santos", "SP"),
    ]
    queried_ids = []

    def fake_daily(property_ids, first_day, last_day):
        queried_ids.append((property_ids, first_day, last_day))
        return [(date(2026, 9, 1), 25)]

    monkeypatch.setattr(db_postgres, "get_organization_consumption_daily", fake_daily)
    tools = _toolset(monkeypatch, access="organizational", properties=properties)
    tool = tools["get_consumption_summary"]
    period_input = {
        "period": "custom",
        "start_date": "2026-09-01",
        "end_date": "2026-09-02",
    }

    ambiguous = tool.invoke({**period_input, "unit_name": "Campus"})
    assert ambiguous["status"] == "ambiguous"
    assert [item["property_id"] for item in ambiguous["candidates"]] == [151, 152]
    assert queried_ids == []

    selected = tool.invoke(
        {**period_input, "unit_name": "Campus", "unit_id": 152}
    )
    assert selected["status"] == "ok"
    assert selected["scope"]["unit"]["property_id"] == 152
    assert queried_ids[0][0] == [152]

    exact_name = tool.invoke({**period_input, "unit_name": "Campus Norte"})
    assert exact_name["scope"]["unit"]["property_id"] == 153
    assert queried_ids[1][0] == [153]

    unauthorized = tool.invoke({**period_input, "unit_id": 999})
    assert unauthorized["status"] == "insufficient_data"
    assert len(queried_ids) == 2


def test_organization_all_units_and_list_only_expose_authorized_property_ids(monkeypatch):
    properties = [
        OrganizationProperty(151, "Campus A", "Sao Paulo", "SP"),
        OrganizationProperty(152, "Campus B", "Campinas", "SP"),
    ]
    queried_ids = []
    monkeypatch.setattr(
        db_postgres,
        "get_organization_consumption_daily",
        lambda ids, start, end: queried_ids.append(list(ids)) or [],
    )
    tools = _toolset(monkeypatch, access="organizational", properties=properties)

    empty = tools["get_consumption_summary"].invoke(
        {
            "period": "custom",
            "start_date": "2026-09-01",
            "end_date": "2026-09-01",
        }
    )
    listed = tools["list_consumption_units"].invoke({})

    assert empty["status"] == "insufficient_data"
    assert empty["metrics"]["total_liters"] is None
    assert queried_ids == [[151, 152]]
    assert [unit["property_id"] for unit in listed["units"]] == [151, 152]
    assert listed["scope"]["user_id_bound"] is True


def test_comparison_reports_values_duration_and_short_previous_month(monkeypatch):
    fixed_now = datetime(2026, 3, 31, 12, tzinfo=UTC)
    monkeypatch.setattr(
        db_postgres,
        "get_organization_consumption_daily",
        lambda ids, first, last: [],
    )
    tools = _toolset(
        monkeypatch,
        access="organizational",
        properties=[OrganizationProperty(151, "Campus", "Sao Paulo", "SP")],
        clock=lambda: fixed_now,
    )
    result = tools["compare_consumption_periods"].invoke(
        {
            "current_period": "this_month",
            "previous_period": "previous_month_same_days",
        }
    )

    assert result["status"] == "insufficient_data"
    assert result["current"]["duration_seconds"] != result["previous"]["duration_seconds"]
    assert result["current"]["data_quality"]["partial_data"] is True
    assert any("durações diferentes" in note for note in result["comparison_notes"])
    assert any("menos dias" in note for note in result["comparison_notes"])
    assert "2026-03-31" in result["current"]["data_quality"]["dates_without_records"]
    assert "2026-02-28" in result["previous"]["data_quality"]["dates_without_records"]


def test_comparison_sums_daily_rows_and_returns_expected_difference_and_percentage(monkeypatch):
    selected = []

    def fake_daily(property_ids, first_day, last_day):
        selected.append((list(property_ids), first_day, last_day))
        if first_day == date(2026, 8, 29):
            return [(date(2026, 8, 31), 250)]
        return [
            (date(2026, 9, 1), 100),
            (date(2026, 9, 1), 50),
            (date(2026, 9, 2), 200),
        ]

    monkeypatch.setattr(db_postgres, "get_organization_consumption_daily", fake_daily)
    tools = _toolset(
        monkeypatch,
        access="organizational",
        properties=[OrganizationProperty(151, "Campus", "Sao Paulo", "SP")],
    )
    result = tools["compare_consumption_periods"].invoke(
        {
            "current_period": "custom",
            "current_start_date": "2026-09-01",
            "current_end_date": "2026-09-03",
            "previous_period": "custom",
            "previous_start_date": "2026-08-29",
            "previous_end_date": "2026-08-31",
            "unit_id": 151,
        }
    )

    assert result["status"] == "ok"
    assert result["current"]["metrics"]["total_liters"] == 350
    assert result["previous"]["metrics"]["total_liters"] == 250
    assert result["comparison"] == {
        "difference_liters": 100,
        "change_percent": 40,
    }
    assert any("quantidades diferentes de dias com registros" in note for note in result["comparison_notes"])
    assert selected == [
        ([151], date(2026, 9, 1), date(2026, 9, 3)),
        ([151], date(2026, 8, 29), date(2026, 8, 31)),
    ]


def test_empty_is_not_zero_and_source_or_data_errors_have_distinct_status(monkeypatch):
    tools = _toolset(monkeypatch)
    monkeypatch.setattr(db_mongo, "get_consumption_history_between", lambda *args: [])
    empty = tools["get_consumption_summary"].invoke({"period": "yesterday"})
    assert empty["status"] == "insufficient_data"
    assert empty["metrics"]["total_liters"] is None
    assert empty["data_quality"]["partial_data"] is True

    zero = _point(datetime(2026, 9, 3, 12, tzinfo=UTC), 0)
    monkeypatch.setattr(db_mongo, "get_consumption_history_between", lambda *args: [zero])
    observed_zero = tools["get_consumption_summary"].invoke({"period": "yesterday"})
    assert observed_zero["status"] == "ok"
    assert observed_zero["metrics"]["total_liters"] == 0

    monkeypatch.setattr(
        db_mongo,
        "get_consumption_history_between",
        lambda *args: (_ for _ in ()).throw(DatabaseQueryError("MongoDB")),
    )
    unavailable = tools["get_consumption_summary"].invoke({"period": "yesterday"})
    assert unavailable["status"] == "source_unavailable"
    assert "MongoDB" not in unavailable["message"]

    monkeypatch.setattr(
        db_mongo,
        "get_consumption_history_between",
        lambda *args: (_ for _ in ()).throw(DatabaseDataError("MongoDB")),
    )
    inconsistent = tools["get_consumption_summary"].invoke({"period": "yesterday"})
    assert inconsistent["status"] == "inconsistent_data"


def test_invalid_period_and_peak_limit_are_reported_without_source_reads(monkeypatch):
    queried = False

    def fail_if_queried(*args):
        nonlocal queried
        queried = True
        return []

    monkeypatch.setattr(db_mongo, "get_consumption_history_between", fail_if_queried)
    tools = _toolset(monkeypatch)

    invalid_period = tools["get_consumption_summary"].invoke(
        {
            "period": "custom",
            "start_date": "2026-09-03",
            "end_date": "2026-09-01",
        }
    )
    invalid_limit = tools["get_consumption_peaks"].invoke(
        {"period": "yesterday", "limit": 11}
    )

    assert invalid_period["status"] == "invalid_input"
    assert invalid_limit["status"] == "invalid_input"
    assert queried is False


def test_zero_length_period_at_local_midnight_does_not_query_sources(monkeypatch):
    local_midnight = datetime(2026, 9, 4, 0, tzinfo=timezone(timedelta(hours=-3)))
    queried = False

    def fail_if_queried(*args):
        nonlocal queried
        queried = True
        raise AssertionError("a consulta não deve executar para período vazio")

    monkeypatch.setattr(db_mongo, "get_consumption_history_between", fail_if_queried)
    monkeypatch.setattr(db_postgres, "get_organization_consumption_daily", fail_if_queried)
    tools = _toolset(monkeypatch, clock=lambda: local_midnight)

    result = tools["get_consumption_summary"].invoke({"period": "today"})

    assert result["status"] == "insufficient_data"
    assert result["period"]["calendar_days_touched"] == 0
    assert any("não contém tempo" in note for note in result["data_quality"]["notes"])
    assert queried is False
