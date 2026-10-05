"""Testes do Agente de Previsão com LLM falso e tools stubadas."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.agents.forecast import ForecastAgent
from app.tools.forecast import calculations as calc
from app.tools.models import ConsumptionPoint, OrganizationProperty
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


def _org_properties() -> list[OrganizationProperty]:
    return [
        OrganizationProperty(property_id=151, name="Unidade Centro", city="Lins", state="SP"),
        OrganizationProperty(property_id=152, name="Unidade Norte", city="Lins", state="SP"),
    ]


@pytest.fixture
def forecast_stubs(monkeypatch):
    monkeypatch.setattr("app.data.db_postgres.get_user_access_kind", lambda uid: "residential")
    monkeypatch.setattr("app.data.db_postgres.user_can_estimate", lambda uid: True)
    monkeypatch.setattr("app.data.db_postgres.get_last_water_bill", lambda uid: None)
    monkeypatch.setattr("app.data.db_postgres.get_user_region_id", lambda uid: 1)
    monkeypatch.setattr("app.data.db_postgres.get_user_property_classification_id", lambda uid: 1)
    monkeypatch.setattr(
        "app.data.db_postgres.get_current_region_rate",
        lambda region_id, classification_id, on_date: Decimal("6.90"),
    )
    monkeypatch.setattr(
        "app.data.db_mongo.get_consumption_history",
        lambda uid, days: _history(30, 100.0),
    )
    monkeypatch.setattr("app.data.db_mongo.get_daily_liters_target", lambda uid: 400.0)


@pytest.fixture
def organizational_stubs(monkeypatch):
    """Organização de teste com 2 unidades, ambas elegíveis (dado real em gold)."""
    monkeypatch.setattr("app.data.db_postgres.get_user_access_kind", lambda uid: "organizational")
    monkeypatch.setattr(
        "app.data.db_postgres.get_user_organization_properties",
        lambda uid: _org_properties(),
    )
    monkeypatch.setattr("app.data.db_postgres.organization_can_estimate", lambda ids: True)
    monkeypatch.setattr(
        "app.data.db_postgres.get_organization_consumption_history",
        lambda ids, days, today: _history(30, 100.0),
    )
    monkeypatch.setattr(
        "app.data.db_postgres.get_organization_last_billed_period",
        lambda ids, today: None,
    )
    monkeypatch.setattr(
        "app.data.db_postgres.get_organization_effective_rate",
        lambda ids, today, window_days=30: Decimal("7.20"),
    )
    monkeypatch.setattr("app.data.db_mongo.get_daily_liters_target", lambda uid: None)


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
    monkeypatch.setattr("app.data.db_postgres.get_user_access_kind", lambda uid: "residential")
    monkeypatch.setattr("app.data.db_postgres.user_can_estimate", lambda uid: False)
    monkeypatch.setattr(
        "app.data.db_mongo.get_consumption_history", lambda uid, days: []
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


def test_calculate_forecast_organizational_single_property(monkeypatch):
    monkeypatch.setattr("app.data.db_postgres.get_user_access_kind", lambda uid: "organizational")
    monkeypatch.setattr(
        "app.data.db_postgres.get_user_organization_properties",
        lambda uid: [OrganizationProperty(property_id=151, name="Unidade Centro", city="Lins", state="SP")],
    )
    monkeypatch.setattr("app.data.db_postgres.organization_can_estimate", lambda ids: True)
    monkeypatch.setattr(
        "app.data.db_postgres.get_organization_consumption_history",
        lambda ids, days, today: _history(30, 100.0),
    )
    monkeypatch.setattr("app.data.db_postgres.get_organization_last_billed_period", lambda ids, today: None)
    monkeypatch.setattr(
        "app.data.db_postgres.get_organization_effective_rate",
        lambda ids, today, window_days=30: Decimal("7.20"),
    )
    monkeypatch.setattr("app.data.db_mongo.get_daily_liters_target", lambda uid: None)

    llm = ScriptedChatModel(
        responses=[
            ai_tool_call("check_can_estimate", {}, "c1"),
            ai_tool_call("calculate_forecast", {}, "c2"),
            ai_final("Estimativa gerada com base na telemetria da unidade."),
        ]
    )
    agent = ForecastAgent(user_id=201, llm=llm, today=TODAY)
    result = agent.run("Faça uma previsão para minha unidade.")

    outputs = {tc.name: tc.output for tc in result.tool_calls}
    assert outputs["check_can_estimate"]["can_estimate"] is True
    assert outputs["calculate_forecast"]["status"] == "ok"


def test_calculate_forecast_organizational_aggregates_all_units_by_default(monkeypatch, organizational_stubs):
    captured: dict = {}

    def _history_stub(ids, days, today):
        captured["ids"] = ids
        return _history(30, 100.0)

    monkeypatch.setattr("app.data.db_postgres.get_organization_consumption_history", _history_stub)

    llm = ScriptedChatModel(
        responses=[
            ai_tool_call("check_can_estimate", {}, "c1"),
            ai_tool_call("calculate_forecast", {}, "c2"),
            ai_final("Estimativa consolidada de todas as unidades da organização."),
        ]
    )
    agent = ForecastAgent(user_id=200, llm=llm, today=TODAY)
    result = agent.run("Como está o consumo geral da nossa organização?")

    assert captured["ids"] == [151, 152]
    outputs = {tc.name: tc.output for tc in result.tool_calls}
    assert outputs["calculate_forecast"]["status"] == "ok"


def test_calculate_forecast_organizational_filters_to_named_unit(monkeypatch, organizational_stubs):
    captured: dict = {}

    def _history_stub(ids, days, today):
        captured["ids"] = ids
        return _history(30, 100.0)

    monkeypatch.setattr("app.data.db_postgres.get_organization_consumption_history", _history_stub)

    llm = ScriptedChatModel(
        responses=[
            ai_tool_call("check_can_estimate", {"property_name": "Centro"}, "c1"),
            ai_tool_call("calculate_forecast", {"property_name": "Centro"}, "c2"),
            ai_final("Estimativa da unidade Centro."),
        ]
    )
    agent = ForecastAgent(user_id=200, llm=llm, today=TODAY)
    agent.run("Como está o consumo da unidade Centro?")

    assert captured["ids"] == [151]


def test_calculate_forecast_organizational_ambiguous_unit_name(organizational_stubs):
    llm = ScriptedChatModel(
        responses=[
            ai_tool_call("calculate_forecast", {"property_name": "Unidade"}, "c1"),
            ai_final("Preciso saber qual unidade você quer dizer: Centro ou Norte?"),
        ]
    )
    agent = ForecastAgent(user_id=200, llm=llm, today=TODAY)
    result = agent.run("Como está o consumo da unidade?")

    output = result.tool_calls[0].output
    assert output["status"] == "ambiguous"
    assert len(output["candidates"]) == 2


def test_calculate_forecast_organizational_unit_not_found(organizational_stubs):
    llm = ScriptedChatModel(
        responses=[
            ai_tool_call("calculate_forecast", {"property_name": "Sul"}, "c1"),
            ai_final("Não encontrei uma unidade com esse nome na organização."),
        ]
    )
    agent = ForecastAgent(user_id=200, llm=llm, today=TODAY)
    result = agent.run("Como está o consumo da unidade Sul?")

    output = result.tool_calls[0].output
    assert output["status"] == "insufficient_data"
    assert "available_units" in output


def test_calculate_forecast_organizational_without_telemetry(monkeypatch, organizational_stubs):
    monkeypatch.setattr("app.data.db_postgres.organization_can_estimate", lambda ids: False)

    llm = ScriptedChatModel(
        responses=[
            ai_tool_call("check_can_estimate", {}, "c1"),
            ai_tool_call("calculate_forecast", {}, "c2"),
            ai_final("Não há dados suficientes para essa organização."),
        ]
    )
    agent = ForecastAgent(user_id=200, llm=llm, today=TODAY)
    result = agent.run("Faça uma previsão para nossa organização.")

    outputs = {tc.name: tc.output for tc in result.tool_calls}
    assert outputs["check_can_estimate"]["can_estimate"] is False
    assert outputs["calculate_forecast"]["status"] == "insufficient_data"


def test_calculate_forecast_user_without_residential_or_organization(monkeypatch):
    monkeypatch.setattr("app.data.db_postgres.get_user_access_kind", lambda uid: "none")

    llm = ScriptedChatModel(
        responses=[
            ai_tool_call("calculate_forecast", {}, "c1"),
            ai_final("Não há dados suficientes para esse usuário."),
        ]
    )
    agent = ForecastAgent(user_id=999, llm=llm, today=TODAY)
    result = agent.run("Faça uma previsão da minha conta.")

    output = result.tool_calls[0].output
    assert output["status"] == "insufficient_data"
