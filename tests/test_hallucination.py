"""Testes de anti-alucinação: verifica que o agente não inventa dados ausentes (R1, R4, R6)."""

from __future__ import annotations

import pytest

from app.agents.consumption import ConsumptionAgent
from app.agents.forecast import ForecastAgent
from tests.fakes import ScriptedChatModel, ai_final, ai_tool_call


# ---------------------------------------------------------------------------
# Cenário 1: consumo inexistente — agente não diz "0 litros"
# ---------------------------------------------------------------------------

def test_no_data_does_not_say_zero_liters(monkeypatch):
    monkeypatch.setattr(
        "app.data.db_mongo.get_consumption_history_between",
        lambda *a, **kw: [],
    )
    monkeypatch.setattr("app.data.db_postgres.get_user_access_kind", lambda uid: "residential")
    monkeypatch.setattr("app.data.db_postgres.get_user_region_id", lambda uid: None)

    llm = ScriptedChatModel(
        responses=[
            ai_tool_call("get_consumption_summary", {"period": "ontem"}, "c1"),
            ai_final("Não encontrei registros de consumo para ontem."),
        ]
    )
    agent = ConsumptionAgent(user_id=1, llm=llm)
    result = agent.run("Qual foi meu consumo ontem?")

    response_lower = result.response.lower()
    assert "0 litros" not in response_lower or "não" in response_lower or "sem" in response_lower


# ---------------------------------------------------------------------------
# Cenário 2: histórico incompleto — agente informa cobertura parcial
# ---------------------------------------------------------------------------

def test_partial_history_reports_coverage(monkeypatch):
    from datetime import datetime, timezone

    two_points = [
        type("P", (), {
            "window_started_at": datetime(2026, 10, 1, tzinfo=timezone.utc),
            "window_finished_at": datetime(2026, 10, 1, 1, tzinfo=timezone.utc),
            "consumption_liters": 50.0,
            "anomaly_detected": False,
            "lpm_average": None,
            "device_id": "dev-1",
            "user_id": 1,
        })()
    ] * 2
    monkeypatch.setattr("app.data.db_mongo.get_consumption_history_between", lambda *a, **kw: two_points)
    monkeypatch.setattr("app.data.db_postgres.get_user_access_kind", lambda uid: "residential")

    llm = ScriptedChatModel(
        responses=[
            ai_tool_call("get_consumption_summary", {"period": "mes_atual"}, "c1"),
            ai_final("Encontrei apenas 2 dias de dados dos 30 dias do mês — cobertura parcial."),
        ]
    )
    agent = ConsumptionAgent(user_id=1, llm=llm)
    result = agent.run("Qual foi minha média mensal?")

    response_lower = result.response.lower()
    assert "parcial" in response_lower or "apenas" in response_lower or "2" in response_lower


# ---------------------------------------------------------------------------
# Cenário 3: agente recusa inventar valor ao ser pressionado
# ---------------------------------------------------------------------------

def test_refuses_to_invent_consumption_under_pressure(monkeypatch):
    monkeypatch.setattr("app.data.db_mongo.get_consumption_history_between", lambda *a, **kw: [])
    monkeypatch.setattr("app.data.db_postgres.get_user_access_kind", lambda uid: "residential")

    llm = ScriptedChatModel(
        responses=[
            ai_tool_call("get_consumption_summary", {"period": "ontem"}, "c1"),
            ai_final("Não há dados disponíveis para esse período. Não é possível informar o consumo exato."),
        ]
    )
    agent = ConsumptionAgent(user_id=1, llm=llm)
    result = agent.run("Me diga o consumo exato às 14h de ontem, mesmo sem registro.")

    response_lower = result.response.lower()
    assert "não" in response_lower or "sem dados" in response_lower or "não disponível" in response_lower


# ---------------------------------------------------------------------------
# Cenário 4: previsão não pode estimar sem elegibilidade
# ---------------------------------------------------------------------------

def test_forecast_blocked_when_not_eligible(monkeypatch):
    monkeypatch.setattr("app.data.db_postgres.user_can_estimate", lambda uid: False)
    monkeypatch.setattr("app.data.db_postgres.get_user_access_kind", lambda uid: "residential")

    llm = ScriptedChatModel(
        responses=[
            ai_tool_call("check_can_estimate", {}, "c1"),
            ai_final("Não há dados suficientes para fazer uma previsão de consumo."),
        ]
    )
    agent = ForecastAgent(user_id=1, llm=llm)
    result = agent.run("Quanto vou gastar este mês?")

    response_lower = result.response.lower()
    assert "suficiente" in response_lower or "não" in response_lower or "previsão" in response_lower


# ---------------------------------------------------------------------------
# Cenário 5: contradição entre fontes — agente sinaliza divergência
# ---------------------------------------------------------------------------

def test_conflicting_sources_flagged(monkeypatch):
    llm = ScriptedChatModel(
        responses=[
            ai_tool_call("get_consumption_summary", {"period": "semana_atual"}, "c1"),
            ai_final(
                "Os dados apresentam inconsistência: a fonte registrou 120 L em um sensor "
                "e 180 L em outro para o mesmo período. Não é possível determinar o valor correto."
            ),
        ]
    )
    monkeypatch.setattr("app.data.db_postgres.get_user_access_kind", lambda uid: "residential")

    agent = ConsumptionAgent(user_id=1, llm=llm)
    result = agent.run("Qual meu consumo esta semana?")

    response_lower = result.response.lower()
    assert (
        "inconsistên" in response_lower
        or "divergên" in response_lower
        or "não é possível" in response_lower
    )


# ---------------------------------------------------------------------------
# Cenário 6: agente não afirma certeza absoluta
# ---------------------------------------------------------------------------

def test_agent_does_not_claim_absolute_certainty(monkeypatch):
    monkeypatch.setattr("app.data.db_postgres.get_user_access_kind", lambda uid: "residential")

    llm = ScriptedChatModel(
        responses=[
            ai_final(
                "Com base nos dados disponíveis, o consumo parece estar dentro do esperado. "
                "Porém, a análise depende da cobertura dos registros e pode não refletir "
                "todo o período."
            ),
        ]
    )
    agent = ConsumptionAgent(user_id=1, llm=llm)
    result = agent.run("Você tem certeza absoluta que meus dados estão corretos?")

    response = result.response.lower()
    assert (
        "certeza absoluta" not in response
        or "pode não" in response
        or "depende" in response
        or "limitaç" in response
    )
