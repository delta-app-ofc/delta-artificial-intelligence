"""O gráfico da previsão não pode sair vazio quando só há o resultado do cálculo."""

from app.agents._runtime import ToolCall
from app.tools.charts import build_forecast_chart

FORECAST = {"status": "ok", "forecast": {
    "projection": {"month_consumption_so_far_liters": 4200.0, "month_projection_liters": 14114.0},
    "target_risk": {"monthly_target_liters": 12000.0},
}}


def test_without_daily_history_it_draws_month_bars_with_data():
    chart = build_forecast_chart([ToolCall("calculate_forecast", {}, FORECAST)])
    assert chart["data"][0]["type"] == "bar"
    assert chart["data"][0]["y"] == [4200.0, 14114.0, 12000.0]


def test_without_target_the_bar_is_left_out():
    forecast = {"status": "ok", "forecast": {"projection": {"month_projection_liters": 100.0}, "target_risk": {}}}
    chart = build_forecast_chart([ToolCall("calculate_forecast", {}, forecast)])
    assert chart["data"][0]["y"] == [100.0]


def test_with_history_it_keeps_the_line_chart():
    history = {"status": "ok", "windows": [{"window_started_at": "2026-11-01T00:00:00", "consumption_liters": 300}]}
    chart = build_forecast_chart([ToolCall("get_consumption_history", {}, history),
                                  ToolCall("calculate_forecast", {}, FORECAST)])
    assert chart["data"][0]["type"] == "scatter"


def test_nothing_to_draw_returns_none():
    assert build_forecast_chart([]) is None
    assert build_forecast_chart([ToolCall("calculate_forecast", {}, {"status": "ok", "forecast": {}})]) is None
