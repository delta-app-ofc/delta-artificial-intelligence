"""Fluxo standalone do agente de consumo sem credenciais ou bancos reais."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.agents._runtime import AgentResult
from app.agents.consumption import ConsumptionAgent
from app.data import db_mongo, db_postgres
from app.services.prompts import consumo_prompt_completo
from app.tools.models import ConsumptionPoint
from tests.fakes import ScriptedChatModel, ai_final, ai_tool_call

UTC = timezone.utc
NOW = datetime(2026, 9, 4, 12, tzinfo=UTC)


def test_prompt_is_built_at_use_with_local_timezone_and_implemented_tools_only():
    prompt = consumo_prompt_completo(now=NOW)

    assert "Agora: 2026-09-04T09:00:00-03:00 (America/Sao_Paulo)" in prompt
    assert "get_consumption_summary" in prompt
    assert "compare_consumption_periods" in prompt
    assert "get_consumption_peaks" in prompt
    assert "list_consumption_units" in prompt
    assert "Redis" not in prompt
    assert "cobertura da fonte não é determinada" in prompt.lower()
    assert "não diagnostica vazamentos" in prompt.lower()


def test_agent_runs_standalone_and_uses_injected_now_for_bound_mongo_query(monkeypatch):
    requested = {}
    monkeypatch.setattr(db_postgres, "get_user_access_kind", lambda user_id: "residential")

    def fake_history(user_id, start, end, finished_before):
        requested.update(user_id=user_id, start=start, end=end, finished_before=finished_before)
        return [
            ConsumptionPoint(
                user_id=11,
                window_started_at=datetime(2026, 9, 3, 10, tzinfo=UTC),
                window_finished_at=datetime(2026, 9, 3, 10, 5, tzinfo=UTC),
                consumption_liters=42,
                anomaly_detected=False,
                lpm_average=1.0,
                device_id="sensor-1",
            )
        ]

    monkeypatch.setattr(db_mongo, "get_consumption_history_between", fake_history)
    llm = ScriptedChatModel(
        responses=[
            ai_tool_call("get_consumption_summary", {"period": "yesterday"}, "c1"),
            ai_final("O consumo registrado ontem foi de 42 litros."),
        ]
    )

    agent = ConsumptionAgent(user_id=11, llm=llm, now=NOW)
    result = agent.run("Quanto consumi ontem?")

    assert isinstance(result, AgentResult)
    assert result.response == "O consumo registrado ontem foi de 42 litros."
    assert [call.name for call in result.tool_calls] == ["get_consumption_summary"]
    assert result.tool_calls[0].output["metrics"]["total_liters"] == 42
    assert requested["user_id"] == 11
    assert requested["finished_before"] == NOW
    assert requested["start"] == datetime(2026, 9, 3, 3, tzinfo=UTC)
    assert requested["end"] == datetime(2026, 9, 4, 3, tzinfo=UTC)
    assert [tool.name for tool in agent.tools] == [
        "get_consumption_summary",
        "compare_consumption_periods",
        "get_consumption_peaks",
        "list_consumption_units",
    ]


def test_agent_rejects_naive_reference_time_and_two_clock_sources():
    with pytest.raises(ValueError, match="fuso horário"):
        ConsumptionAgent(user_id=11, llm=object(), now=datetime(2026, 9, 4, 12))
    with pytest.raises(ValueError, match="now ou clock"):
        ConsumptionAgent(
            user_id=11,
            llm=object(),
            now=NOW,
            clock=lambda: NOW,
        )


def test_agent_uses_one_clock_snapshot_for_prompt_and_every_tool(monkeypatch):
    clock_calls = 0
    prompt_times = []
    source_times = []

    def advancing_clock():
        nonlocal clock_calls
        clock_calls += 1
        return NOW if clock_calls == 1 else NOW + timedelta(days=1)

    def prompt_stub(*, now, timezone_name):
        prompt_times.append(now)
        return f"now={now.isoformat()} timezone={timezone_name}"

    def history_stub(user_id, start, end, finished_before):
        source_times.append(finished_before)
        return []

    monkeypatch.setattr("app.agents.consumption.consumo_prompt_completo", prompt_stub)
    monkeypatch.setattr(db_postgres, "get_user_access_kind", lambda user_id: "residential")
    monkeypatch.setattr(db_mongo, "get_consumption_history_between", history_stub)
    llm = ScriptedChatModel(
        responses=[
            ai_tool_call("get_consumption_summary", {"period": "today"}, "c1"),
            ai_final("Não encontrei registros de consumo para hoje."),
        ]
    )

    result = ConsumptionAgent(user_id=11, llm=llm, clock=advancing_clock).run(
        "Quanto consumi hoje?"
    )

    assert result.tool_calls[0].output["status"] == "insufficient_data"
    assert clock_calls == 1
    assert prompt_times == [NOW]
    assert source_times == [NOW]
