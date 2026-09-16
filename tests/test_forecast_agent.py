"""Testes do Agente de Previsão com LLM falso e tools stubadas."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.agents.forecast import ForecastAgent
from app.tools.forecast import calculations as calc
from app.tools.models import ConsumptionPoint
from tests.fakes import ScriptedChatModel, ai_final, ai_tool_call

TODAY = date(2026, 9, 15)


def _history(days: int, liters_per_day: float) -> list[ConsumptionPoint]:
    points = []
    for i in range(days):
        day = TODAY - timedelta(days=days - i)
        start = datetime(day.year, day.month, day.day, 12, 0, 0)
        points.append(
            ConsumptionPoint(
                user_id=999,
                window_started_at=start,
                window_finished_at=start + timedelta(minutes=5),
                consumption_liters=liters_per_day,
                anomaly_detected=False,
            )
        )
    return points


@pytest.fixture
def forecast_stubs(monkeypatch):
    monkeypatch.setattr("app.tools.db_postgres.user_can_estimate", lambda uid: True)
    monkeypatch.setattr("app.tools.db_postgres.get_last_water_bill", lambda uid: None)
    monkeypatch.setattr("app.tools.db_postgres.get_user_region_id", lambda uid: 1)
    monkeypatch.setattr(
        "app.tools.db_postgres.get_current_region_rate",
        lambda region_id, on_date: Decimal("6.90"),
    )
    monkeypatch.setattr(
        "app.tools.db_mongo.get_consumption_history",
        lambda uid, days: _history(30, 100.0),
    )
    monkeypatch.setattr("app.tools.db_mongo.get_daily_liters_target", lambda uid: 400.0)


def test_response_number_matches_the_calculation_tool(forecast_stubs):
    expected = calc.calculate_full_forecast(
        can_estimate=True, history=_history(30, 100.0), last_bill=None,
        region_rate=Decimal("6.90"), daily_target=400.0, today=TODAY,
    )
    projection = expected.projection.month_projection_liters

    llm = ScriptedChatModel(
        responses=[
            ai_tool_call("check_can_estimate", {}, "c1"),
            ai_tool_call("calculate_forecast", {}, "c2"),
            ai_final(
                f"Com base no histórico consultado, o consumo projetado até o fim "
                f"do mês é de aproximadamente {projection} litros. É uma estimativa."
            ),
        ]
    )
    agent = ForecastAgent(user_id=11, llm=llm, today=TODAY)
    result = agent.run("Quanto devo consumir até o fim do mês?")

    assert [tc.name for tc in result.tool_calls] == [
        "check_can_estimate",
        "calculate_forecast",
    ]
    calc_output = result.tool_calls[-1].output
    assert calc_output["status"] == "ok"
    # A tool produziu, de forma independente, o mesmo número citado na resposta.
    assert calc_output["forecast"]["projection"]["month_projection_liters"] == projection
    assert str(projection) in result.response


def test_can_estimate_false_guard_invents_no_number(monkeypatch):
    monkeypatch.setattr("app.tools.db_postgres.user_can_estimate", lambda uid: False)
    monkeypatch.setattr(
        "app.tools.db_mongo.get_consumption_history", lambda uid, days: []
    )

    llm = ScriptedChatModel(
        responses=[
            ai_tool_call("check_can_estimate", {}, "c1"),
            ai_tool_call("calculate_forecast", {}, "c2"),
            ai_final(
                "Não há dados suficientes para realizar uma estimativa de consumo "
                "para este usuário."
            ),
        ]
    )
    agent = ForecastAgent(user_id=150, llm=llm, today=TODAY)
    result = agent.run("Faça uma previsão da minha conta.")

    outputs = {tc.name: tc.output for tc in result.tool_calls}
    assert outputs["check_can_estimate"]["can_estimate"] is False
    assert outputs["calculate_forecast"]["status"] == "insufficient_data"
    assert not re.search(r"\d", result.response)


def test_readable_log_lists_the_tools(forecast_stubs):
    llm = ScriptedChatModel(
        responses=[
            ai_tool_call("get_consumption_history", {"days": 30}, "c1"),
            ai_final("Consultei o histórico recente."),
        ]
    )
    agent = ForecastAgent(user_id=11, llm=llm, today=TODAY)
    result = agent.run("Como está meu consumo recente?")

    assert result.tool_calls[0].name == "get_consumption_history"
    assert result.tool_calls[0].input == {"days": 30}
    assert "get_consumption_history" in result.readable_log()
