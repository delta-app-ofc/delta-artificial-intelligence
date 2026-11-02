"""Simulação de meta e cenários de investimento, sem banco nem LLM reais."""

import dataclasses
from datetime import date
from unittest.mock import patch

from app.tools.forecast import calculations as calc
from app.tools.models import OrganizationProperty
from app.tools.forecast import tools as forecast_tools

TODAY = date(2026, 11, 10)  # novembro: 30 dias
UNIT = OrganizationProperty(1, "Filial Alfa", "Lins", "SP")


def test_raising_the_target_removes_the_risk():
    out = calc.compare_target_change(14000.0, 400.0, 500.0, TODAY)
    assert out.current.monthly_target_liters == 12000.0 and out.current.at_risk is True
    assert out.simulated.monthly_target_liters == 15000.0 and out.simulated.at_risk is False
    assert out.monthly_target_difference_liters == 3000.0


def test_without_current_target_only_the_simulated_one_is_assessed():
    out = calc.compare_target_change(14000.0, None, 500.0, TODAY)
    assert out.current.assessable is False and out.simulated.assessable is True
    assert out.monthly_target_difference_liters is None


def test_invalid_target_is_rejected():
    for value in (0, -5):
        try:
            calc.compare_target_change(14000.0, 400.0, value, TODAY)
        except ValueError:
            continue
        raise AssertionError("meta inválida deveria ser recusada")


def test_investment_savings_in_liters():
    assert calc.estimate_investment_savings(500.0, 12.0) == 21900.0


@dataclasses.dataclass
class _Projection:
    month_projection_liters: float = 14000.0
    daily_average_liters: float = 500.0


@dataclasses.dataclass
class _Risk:
    monthly_target_liters: float | None = 12000.0


@dataclasses.dataclass
class _Forecast:
    has_enough_history: bool = True
    projection: _Projection = dataclasses.field(default_factory=_Projection)
    target_risk: _Risk = dataclasses.field(default_factory=_Risk)


def _tools(access_kind="organizational"):
    return {t.name: t for t in forecast_tools.build_tools(7, TODAY, access_kind)}


def _run(name, args, forecast=None, access_kind="residential", scenarios=None):
    pg, mongo = forecast_tools.db_postgres, forecast_tools.db_mongo
    with (
        patch.object(pg, "user_can_estimate", return_value=True),
        patch.object(pg, "get_last_water_bill", return_value=None),
        patch.object(pg, "get_user_region_id", return_value=None),
        patch.object(pg, "get_user_property_classification_id", return_value=None),
        patch.object(pg, "get_investment_scenarios", return_value=scenarios or []),
        patch.object(pg, "get_user_organization_properties", return_value=[UNIT]),
        patch.object(pg, "organization_can_estimate", return_value=True),
        patch.object(pg, "get_organization_consumption_history", return_value=[]),
        patch.object(pg, "get_organization_last_billed_period", return_value=None),
        patch.object(pg, "get_organization_effective_rate", return_value=None),
        # Funções que a main acrescentou à leitura de histórico (Mongo primeiro, view como reserva).
        patch.object(pg, "get_authorized_device_ids", return_value=[], create=True),
        patch.object(pg, "get_residential_consumption_history", return_value=[], create=True),
        patch.object(mongo, "get_consumption_history_by_devices", return_value=[], create=True),
        patch.object(mongo, "get_daily_liters_target", return_value=None),
        patch.object(mongo, "get_consumption_history", return_value=[]),
        patch.object(forecast_tools.calc, "calculate_full_forecast", return_value=forecast or _Forecast()),
    ):
        return _tools(access_kind)[name].invoke(args)


def test_target_tool_compares_and_says_nothing_was_changed():
    out = _run("simulate_target_change", {"new_daily_target": 500})
    assert out["status"] == "ok"
    assert out["comparison"]["current"]["at_risk"] is True
    assert out["comparison"]["simulated"]["at_risk"] is False
    assert any("não foi alterada" in a for a in out["assumptions"])


def test_target_tool_needs_history_and_valid_value():
    assert _run("simulate_target_change", {"new_daily_target": 500},
                forecast=_Forecast(has_enough_history=False))["status"] == "insufficient_data"
    assert _run("simulate_target_change", {"new_daily_target": 0})["status"] == "error"


SCENARIOS = [{"name": "AERADORES", "investment_value": 15000.0, "reduction_pct": 12.0,
              "annual_savings_value": 22500.0, "payback_months": 8.0, "description": None}]


def test_investments_are_for_organizations_with_computed_liters():
    out = _run("get_investment_scenarios", {}, access_kind="organizational", scenarios=[dict(s) for s in SCENARIOS])
    assert out["status"] == "ok"
    item = out["scenarios"][0]
    assert item["payback_months"] == 8.0
    assert item["estimated_liters_saved_per_year"] == 21900.0  # 500 L/dia x 365 x 12%


def test_investments_without_history_keep_registered_values_only():
    out = _run("get_investment_scenarios", {}, forecast=_Forecast(has_enough_history=False),
               access_kind="organizational", scenarios=[dict(s) for s in SCENARIOS])
    assert out["scenarios"][0]["estimated_liters_saved_per_year"] is None


def test_investments_empty_catalog():
    out = _run("get_investment_scenarios", {}, access_kind="organizational", scenarios=[])
    assert out["status"] == "insufficient_data"


def test_investments_not_applicable_for_residential():
    out = _run("get_investment_scenarios", {}, access_kind="residential")
    assert out["status"] == "not_applicable"


def test_tools_hide_user_id():
    assert all("user_id" not in t.args for t in _tools().values())
