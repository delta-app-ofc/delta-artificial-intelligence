"""Testa a leitura de hábitos pelos agentes de Previsão e Vazamento (somente leitura)."""

from datetime import date
from unittest.mock import patch

from app.tools.forecast import tools as forecast_tools
from app.tools.habits.calculations import summarize_habit_baseline
from app.tools.leak import tools as leak_tools

HABITS = [
    {"name": "LAVAR CARRO", "category": "LIMPEZA", "frequency": 2, "days": ["SEGUNDA", "SEXTA"],
     "start_time": "18:00", "end_time": "19:00", "estimated_liters": None},
    {"name": "REGAR PLANTAS", "category": "JARDINAGEM", "frequency": 1, "days": ["SEGUNDA"],
     "start_time": None, "end_time": None, "estimated_liters": 30.0},
]


def test_baseline_uses_catalog_and_registered_liters():
    out = summarize_habit_baseline(HABITS)
    assert out["liters_per_week"] == 430.0          # 2 x 200 + 1 x 30
    assert out["liters_per_month"] == 1861.9        # 430 x 4,33
    assert out["liters_per_day_of_week"] == {"SEGUNDA": 230.0, "SEXTA": 200.0}
    sources = {h["name"]: h["liters_source"] for h in out["habits"]}
    assert sources == {"LAVAR CARRO": "referência", "REGAR PLANTAS": "cadastro"}


def _forecast_tool(access_kind="residential"):
    tools = forecast_tools.build_tools(7, date(2026, 11, 10), access_kind)
    return {t.name: t for t in tools}["get_habit_baseline"]


def test_forecast_baseline_residential_with_and_without_habits():
    with patch.object(forecast_tools.db_postgres, "get_user_habits", return_value=HABITS) as get:
        out = _forecast_tool().invoke({})
    get.assert_called_once_with(7)
    assert out["status"] == "ok" and out["liters_per_week"] == 430.0

    with patch.object(forecast_tools.db_postgres, "get_user_habits", return_value=[]):
        assert _forecast_tool().invoke({})["status"] == "insufficient_data"


def test_forecast_baseline_organization_does_not_read_habits():
    with patch.object(forecast_tools.db_postgres, "get_user_habits") as get:
        out = _forecast_tool("organizational").invoke({})
    assert out["status"] == "not_applicable"
    get.assert_not_called()


def test_forecast_baseline_does_not_change_the_forecast_calculation():
    # A tool não toca nas funções de cálculo da previsão.
    with (
        patch.object(forecast_tools.db_postgres, "get_user_habits", return_value=HABITS),
        patch.object(forecast_tools.calc, "calculate_full_forecast") as calculate,
    ):
        _forecast_tool().invoke({})
    calculate.assert_not_called()


def _leak_tool(access_kind="residential"):
    return {t.name: t for t in leak_tools.build_tools(7, access_kind)}["get_habit_windows"]


def test_leak_habit_windows_by_day_and_schedule_flag():
    day_habits = [{"name": "LAVAR CARRO", "frequency": 2, "start_time": "18:00",
                   "end_time": "19:00", "estimated_liters": None},
                  {"name": "REGAR PLANTAS", "frequency": 1, "start_time": None,
                   "end_time": None, "estimated_liters": None}]
    with patch.object(leak_tools.db_postgres, "get_habits_by_weekday", return_value=day_habits) as get:
        out = _leak_tool().invoke({"day": "seg"})
    get.assert_called_once_with(7, "SEGUNDA")
    assert [h["has_schedule"] for h in out["habits"]] == [True, False]
    assert "não prova nem afasta vazamento" in out["note"]


def test_leak_habit_windows_edge_cases():
    assert _leak_tool("organizational").invoke({})["status"] == "not_applicable"
    assert _leak_tool().invoke({"day": "feriado"})["status"] == "error"
    with patch.object(leak_tools.db_postgres, "get_user_habits", return_value=[]):
        assert _leak_tool().invoke({})["status"] == "insufficient_data"


def test_leak_tools_keep_existing_ones_and_hide_user_id():
    tools = {t.name: t for t in leak_tools.build_tools(7, "residential")}
    assert {"get_anomalous_windows", "get_alerts_history", "summarize_anomalous_windows",
            "get_habit_windows"} <= set(tools)
    assert all("user_id" not in t.args for t in tools.values())
