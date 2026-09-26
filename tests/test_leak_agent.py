"""Testes do Agente de Vazamento com LLM falso e tools stubadas."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.agents.leak import LeakAgent
from app.services.prompts import vazamento_prompt_completo
from app.tools.models import Alert, ConsumptionPoint
from tests.fakes import ScriptedChatModel, ai_final, ai_tool_call

NOW = datetime.now(timezone.utc)


def _anomalous_window(hours_ago: int) -> ConsumptionPoint:
    start = NOW - timedelta(hours=hours_ago)
    return ConsumptionPoint(
        user_id=14,
        window_started_at=start,
        window_finished_at=start + timedelta(minutes=5),
        consumption_liters=18.0,
        anomaly_detected=True,
        lpm_average=3.6,
        device_id="ESP3214",
    )


def _active_alert() -> Alert:
    return Alert(
        user_id=14,
        device_id="ESP3214",
        alert_type="vazamento_continuo",
        triggered_at=NOW - timedelta(days=2),
        resolved_at=None,
        severity="high",
    )


def test_prompt_forbids_definitive_diagnosis():
    prompt = vazamento_prompt_completo()
    assert "Existe um vazamento." in prompt
    assert "não" in prompt.lower()
    assert "possível vazamento" in prompt.lower()


def test_leak_sign_present_model_receives_the_signals(monkeypatch):
    monkeypatch.setattr(
        "app.data.db_mongo.get_anomalous_consumption_windows",
        lambda uid, days: [_anomalous_window(3), _anomalous_window(27), _anomalous_window(51)],
    )
    monkeypatch.setattr(
        "app.data.db_mongo.get_alerts_history",
        lambda uid, days, only_active=False: [_active_alert()],
    )

    ok_response = (
        "Os dados apresentam um padrão de consumo contínuo de madrugada que pode "
        "ser compatível com um possível vazamento. Isso não é um diagnóstico "
        "definitivo; recomenda-se verificar a instalação."
    )
    llm = ScriptedChatModel(
        responses=[
            ai_tool_call("get_anomalous_windows", {"days": 30}, "c1"),
            ai_tool_call("get_alerts_history", {"days": 30, "only_active": True}, "c2"),
            ai_final(ok_response),
        ]
    )
    agent = LeakAgent(user_id=14, llm=llm)
    result = agent.run("Tenho algum indício de vazamento?")

    outputs = {tc.name: tc.output for tc in result.tool_calls}
    assert outputs["get_anomalous_windows"]["total_anomalous_windows"] == 3
    assert outputs["get_alerts_history"]["total_alerts"] == 1
    assert outputs["get_alerts_history"]["alerts"][0]["alert_type"] == "vazamento_continuo"
    assert "diagnóstico definitivo" in result.response.lower()
    assert "existe um vazamento" not in result.response.lower()


def test_no_leak_sign(monkeypatch):
    monkeypatch.setattr(
        "app.data.db_mongo.get_anomalous_consumption_windows", lambda uid, days: []
    )
    monkeypatch.setattr(
        "app.data.db_mongo.get_alerts_history",
        lambda uid, days, only_active=False: [],
    )

    llm = ScriptedChatModel(
        responses=[
            ai_tool_call("get_anomalous_windows", {"days": 30}, "c1"),
            ai_tool_call("get_alerts_history", {"days": 30}, "c2"),
            ai_final(
                "Os dados analisados não apresentaram evidências suficientes de um "
                "comportamento compatível com vazamento."
            ),
        ]
    )
    agent = LeakAgent(user_id=15, llm=llm)
    result = agent.run("Tenho algum indício de vazamento?")

    outputs = {tc.name: tc.output for tc in result.tool_calls}
    assert outputs["get_anomalous_windows"]["status"] == "insufficient_data"
    assert outputs["get_anomalous_windows"]["total_anomalous_windows"] == 0
    assert "evidências suficientes" in result.response.lower()


def test_no_data_states_the_limitation(monkeypatch):
    def _error(*args, **kwargs):
        raise RuntimeError("mongo indisponível")

    monkeypatch.setattr(
        "app.data.db_mongo.get_anomalous_consumption_windows", _error
    )

    llm = ScriptedChatModel(
        responses=[
            ai_tool_call("get_anomalous_windows", {"days": 30}, "c1"),
            ai_final("Não há dados suficientes para analisar esse período."),
        ]
    )
    agent = LeakAgent(user_id=14, llm=llm)
    result = agent.run("Verifique a última semana.")

    # A exceção da tool vira registro (status error), não quebra o agente.
    assert result.tool_calls[0].output["status"] == "error"
    assert "não há dados suficientes" in result.response.lower()
