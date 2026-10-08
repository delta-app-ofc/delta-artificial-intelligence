"""Testes do Agente de Hábitos com LLM falso e tools stubadas."""

from __future__ import annotations

import pytest

from app.agents.habits import HabitsAgent
from tests.fakes import ScriptedChatModel, ai_final, ai_tool_call


_HABITS = [
    {"name": "BANHO LONGO", "frequency": 3, "days": ["SEGUNDA", "QUARTA", "SEXTA"]},
    {"name": "LAVAR ROUPA", "frequency": 1, "days": ["SÁBADO"]},
]


@pytest.fixture
def habits_stubs(monkeypatch):
    monkeypatch.setattr(
        "app.data.db_postgres.get_user_habits",
        lambda uid: _HABITS,
    )
    monkeypatch.setattr(
        "app.data.db_postgres.get_habits_by_weekday",
        lambda uid, day: [h for h in _HABITS if day in h["days"]],
    )


def test_list_habits_returns_all(habits_stubs):
    llm = ScriptedChatModel(
        responses=[
            ai_tool_call("list_habits", {}, "c1"),
            ai_final("Você tem 2 hábitos cadastrados: Banho Longo e Lavar Roupa."),
        ]
    )
    agent = HabitsAgent(user_id=1, llm=llm)
    result = agent.run("Quais são meus hábitos?")

    assert result.tool_calls[0].name == "list_habits"
    output = result.tool_calls[0].output
    assert output["status"] == "ok"
    assert len(output["habits"]) == 2
    assert "Banho Longo" in result.response or "banho" in result.response.lower()


def test_chart_data_is_populated_after_list_habits(habits_stubs):
    llm = ScriptedChatModel(
        responses=[
            ai_tool_call("list_habits", {}, "c1"),
            ai_final("Seus hábitos estão listados acima."),
        ]
    )
    agent = HabitsAgent(user_id=1, llm=llm)
    result = agent.run("Mostre meus hábitos com gráfico.")

    assert result.chart_data is not None
    assert "data" in result.chart_data


def test_get_habits_by_day_monday(habits_stubs):
    llm = ScriptedChatModel(
        responses=[
            ai_tool_call("get_habits_by_day", {"day": "segunda"}, "c1"),
            ai_final("Na segunda você costuma tomar banho longo."),
        ]
    )
    agent = HabitsAgent(user_id=1, llm=llm)
    result = agent.run("O que eu faço na segunda?")

    output = result.tool_calls[0].output
    assert output["status"] == "ok"
    assert output["day"] == "SEGUNDA"
    assert any(h["name"] == "BANHO LONGO" for h in output["habits"])


def test_no_habits_returns_insufficient_data(monkeypatch):
    monkeypatch.setattr("app.data.db_postgres.get_user_habits", lambda uid: [])

    llm = ScriptedChatModel(
        responses=[
            ai_tool_call("list_habits", {}, "c1"),
            ai_final("Você não tem hábitos cadastrados no sistema."),
        ]
    )
    agent = HabitsAgent(user_id=99, llm=llm)
    result = agent.run("Quais meus hábitos?")

    output = result.tool_calls[0].output
    assert output["status"] == "insufficient_data"


def test_invalid_day_returns_error(habits_stubs):
    llm = ScriptedChatModel(
        responses=[
            ai_tool_call("get_habits_by_day", {"day": "lunedi"}, "c1"),
            ai_final("Não reconheci esse dia da semana."),
        ]
    )
    agent = HabitsAgent(user_id=1, llm=llm)
    result = agent.run("O que faço na lunedi?")

    output = result.tool_calls[0].output
    assert output["status"] == "error"
    assert "não reconhecido" in output["message"].lower()


def test_chart_data_is_none_when_no_list_habits_called(habits_stubs):
    llm = ScriptedChatModel(
        responses=[
            ai_tool_call("get_habits_by_day", {"day": "sábado"}, "c1"),
            ai_final("No sábado você lava roupa."),
        ]
    )
    agent = HabitsAgent(user_id=1, llm=llm)
    result = agent.run("O que faço no sábado?")

    assert result.chart_data is None
