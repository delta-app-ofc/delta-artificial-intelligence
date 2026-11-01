"""Testa a simulação "e se" do consumo sem banco nem LLM reais."""

import dataclasses
from unittest.mock import patch

import pytest

from app.agents._runtime import ToolCall
from app.tools.charts import build_simulation_chart
from app.tools.forecast import tools as forecast_tools
from app.tools.simulation.calculations import simulate_percentage_change


def test_ten_percent_drop_gives_the_difference_in_liters():
    s = simulate_percentage_change(200, -10, 30)
    assert s.base_period_liters == 6000.0
    assert s.scenario_period_liters == 5400.0
    assert s.difference_liters == -600.0
    assert s.scenario_daily_liters == 180.0


def test_increase_and_zero_change():
    assert simulate_percentage_change(100, 25, 10).difference_liters == 250.0
    assert simulate_percentage_change(100, 0, 10).difference_liters == 0.0


@pytest.mark.parametrize("baseline,pct,days", [(0, -10, 30), (100, -100, 30), (100, -10, 0), (100, -10, 400)])
def test_invalid_inputs_are_rejected(baseline, pct, days):
    with pytest.raises(ValueError):
        simulate_percentage_change(baseline, pct, days)


def _tool():
    tools = forecast_tools.build_tools(7, __import__("datetime").date(2026, 11, 10), "residential")
    return {t.name: t for t in tools}


@dataclasses.dataclass
class _Projection:
    daily_average_liters: float


@dataclasses.dataclass
class _Forecast:
    has_enough_history: bool
    projection: _Projection


def _forecast_ok(enough=True, daily=200.0):
    return _Forecast(enough, _Projection(daily))


def _simulate(forecast, args, can_estimate=True):
    """Roda a tool com o banco e o cálculo da previsão substituídos."""
    pg, mongo = forecast_tools.db_postgres, forecast_tools.db_mongo
    with (
        patch.object(pg, "user_can_estimate", return_value=can_estimate),
        patch.object(pg, "get_last_water_bill", return_value=None),
        patch.object(pg, "get_user_region_id", return_value=None),
        patch.object(pg, "get_user_property_classification_id", return_value=None),
        patch.object(mongo, "get_daily_liters_target", return_value=None),
        patch.object(mongo, "get_consumption_history", return_value=[]),
        patch.object(forecast_tools.calc, "calculate_full_forecast", return_value=forecast),
    ):
        return _tool()["simulate_consumption_change"].invoke(args)


def test_tool_uses_the_forecast_baseline_and_lists_assumptions():
    out = _simulate(_forecast_ok(), {"change_pct": -10})
    assert out["status"] == "ok"
    assert out["scenario"]["difference_liters"] == -600.0
    assert len(out["assumptions"]) >= 3


def test_tool_does_not_simulate_without_history():
    out = _simulate(_forecast_ok(enough=False), {"change_pct": -10})
    assert out["status"] == "insufficient_data"
    assert "scenario" not in out


def test_tool_does_not_simulate_when_user_cannot_estimate():
    out = _simulate(_forecast_ok(), {"change_pct": -10}, can_estimate=False)
    assert out["status"] == "insufficient_data"
    assert "scenario" not in out


def test_tool_rejects_invalid_values_and_hides_user_id():
    assert _simulate(_forecast_ok(), {"change_pct": -100})["status"] == "error"
    assert _simulate(_forecast_ok(), {"change_pct": -10, "days": 0})["status"] != "ok"
    assert "user_id" not in _tool()["simulate_consumption_change"].args


def test_chart_comes_only_from_structured_tool_data():
    scenario = simulate_percentage_change(200, -10, 30)
    call = ToolCall("simulate_consumption_change", {"change_pct": -10},
                    {"status": "ok", "scenario": dataclasses.asdict(scenario)})
    chart = build_simulation_chart([call])
    assert chart["data"][0]["y"] == [6000.0, 5400.0]
    assert build_simulation_chart([ToolCall("simulate_consumption_change", {}, {"status": "insufficient_data"})]) is None
