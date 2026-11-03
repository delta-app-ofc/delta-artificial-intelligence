"""A conta anterior só é alternativa quando não existem leituras no período."""
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest

from app.tools.forecast import calculations as calc, tools
from app.tools.exceptions import DatabaseConnectionError, DatabaseDataError, RegionRateNotFound
from app.tools.models import ConsumptionPoint, LastWaterBill, OrganizationProperty

TODAY = date(2026, 4, 10)
BILL = LastWaterBill(7, date(2026, 3, 1), Decimal("80"), Decimal("16"))


def points(days=1, liters=100):
    return [ConsumptionPoint(7, datetime(2026, 4, 9) - timedelta(days=i),
                             datetime(2026, 4, 9, 1) - timedelta(days=i), liters, False)
            for i in range(days)]


@pytest.fixture
def sources(monkeypatch):
    pg, mongo = tools.db_postgres, tools.db_mongo
    bill = Mock(return_value=BILL)
    data = {"history": points(), "error": None, "rate": Decimal("5")}

    def read(*args):
        if data["error"]:
            raise data["error"]
        return data["history"]

    def rate(*args):
        if data["rate"] is None:
            raise RegionRateNotFound("Tarifa ausente")
        return data["rate"]

    monkeypatch.setattr(mongo, "get_daily_liters_target", lambda uid: 200)
    monkeypatch.setattr(mongo, "get_consumption_history", read)
    monkeypatch.setattr(mongo, "get_consumption_history_by_devices", read)
    monkeypatch.setattr(pg, "get_residential_consumption_history", read)
    monkeypatch.setattr(pg, "get_organization_consumption_history", read)
    monkeypatch.setattr(pg, "get_last_water_bill", bill)
    monkeypatch.setattr(pg, "get_organization_last_billed_period", bill)
    monkeypatch.setattr(pg, "user_can_estimate", lambda uid: True)
    monkeypatch.setattr(pg, "organization_can_estimate", lambda *a: True)
    monkeypatch.setattr(pg, "get_user_region_id", lambda uid: 1)
    monkeypatch.setattr(pg, "get_user_property_classification_id", lambda uid: 1)
    monkeypatch.setattr(pg, "get_current_region_rate", rate)
    monkeypatch.setattr(pg, "get_organization_effective_rate", lambda *a: data["rate"])
    monkeypatch.setattr(pg, "get_user_organization_properties", lambda uid: [OrganizationProperty(10, "Alfa", "São Paulo", "SP")])
    monkeypatch.setattr(pg, "get_authorized_device_ids", lambda *a: ["DEVICE-1"])
    return data, bill


def forecast(kind):
    tool = next(t for t in tools.build_tools(7, TODAY, kind) if t.name == "calculate_forecast")
    return tool.invoke({})["forecast"]


@pytest.mark.parametrize("kind", ["residential", "organizational"])
@pytest.mark.parametrize("days", [1, 6, 7])
def test_any_history_skips_the_bill_query(sources, kind, days):
    data, bill = sources
    data["history"] = points(days)
    result = forecast(kind)
    assert result["bill"]["base"] == "history_projection"
    bill.assert_not_called()
    assert result["has_enough_history"] is (days >= 7)
    if days < 7:
        assert any("Histórico curto" in note for note in result["notes"])


@pytest.mark.parametrize("kind", ["residential", "organizational"])
def test_only_empty_history_reads_and_uses_last_bill(sources, kind):
    data, bill = sources
    data["history"] = []
    result = forecast(kind)
    bill.assert_called_once()
    assert result["bill"]["base"] == "last_bill"
    assert result["bill"]["estimated_value"] == 80
    assert any("referência" in note for note in result["notes"])


@pytest.mark.parametrize("kind", ["residential", "organizational"])
def test_missing_rate_keeps_liters_but_does_not_use_bill(sources, kind):
    data, bill = sources
    data["rate"] = None
    result = forecast(kind)
    assert result["bill"] is None
    assert result["projection"]["month_projection_liters"] == 2100
    assert any("Sem tarifa para converter" in note for note in result["notes"])
    bill.assert_not_called()


@pytest.mark.parametrize("kind", ["residential", "organizational"])
def test_recorded_zero_does_not_use_bill(sources, kind):
    data, bill = sources
    data["history"] = points(liters=0)
    result = forecast(kind)
    assert result["bill"]["estimated_value"] == 0
    assert result["bill"]["base"] == "history_projection"
    bill.assert_not_called()


@pytest.mark.parametrize("error", [DatabaseConnectionError("MongoDB"), DatabaseDataError("MongoDB")])
def test_unreadable_history_is_not_treated_as_empty(sources, error):
    data, bill = sources
    data["error"] = error
    with pytest.raises(type(error)):
        forecast("residential")
    bill.assert_not_called()


def test_no_history_and_no_bill_gives_no_monetary_estimate(sources):
    data, bill = sources
    data["history"] = []
    bill.return_value = None
    result = forecast("residential")
    assert result["bill"] is None
    assert any("Sem histórico de consumo e sem conta anterior" in note for note in result["notes"])


def test_readable_sql_backup_history_also_has_priority(sources, monkeypatch):
    _, bill = sources
    def unavailable(*a):
        raise DatabaseConnectionError("MongoDB")
    monkeypatch.setattr(tools.db_mongo, "get_consumption_history", unavailable)
    result = forecast("residential")
    assert result["bill"]["base"] == "history_projection"
    bill.assert_not_called()
