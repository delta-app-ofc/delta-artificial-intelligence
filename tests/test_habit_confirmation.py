"""Confirmação de hábitos com grafo real e banco/modelos substituídos."""

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.agents.judge import JudgeResult
from app.graph import confirmations, workflow as graph
from app.graph.router import RoutingDecision
from app.tools.exceptions import DatabaseConnectionError, HabitConflictError
from app.tools.habits import tools as habit_tools

GOOD = {"name": "lavar roupas", "days": ["seg", "sexta"], "start_time": "18h", "end_time": "19h"}
PARAMS = {"name": "LAVAR ROUPA", "frequency": 2, "days": ["SEGUNDA", "SEXTA"],
          "start_time": "18:00", "end_time": "19:00"}
DONE = "Pronto! Cadastrei o hábito Lavar Roupa."


@pytest.fixture
def pipeline(monkeypatch):
    config = SimpleNamespace(confirmation_interrupt_enabled=True, bill_registration_enabled=False)
    for module in (graph, confirmations, habit_tools):
        monkeypatch.setattr(module, "get_settings", lambda: config)
    write = MagicMock(return_value={"habit_id": 41, **PARAMS})
    monkeypatch.setattr(habit_tools.db_postgres, "create_habit", write)
    monkeypatch.setattr(habit_tools.db_postgres, "get_user_access_kind", lambda uid: "residential")
    monkeypatch.setattr(graph, "resolve_access_kind", lambda uid: "residential")
    monkeypatch.setattr(graph, "classify_input", lambda question: None)
    monkeypatch.setattr(graph, "load_history_validated", lambda *a: [])
    monkeypatch.setattr(graph, "build_context", lambda *a: {"recent_messages": [], "relevant_memory": []})
    monkeypatch.setattr(graph, "classify", lambda *a: RoutingDecision(
        intent="habits", complexity="simple", agents=["habits"]))
    judge = SimpleNamespace(run=lambda *a, **kw: JudgeResult(
        decision="approve", status="evaluated", justification="teste", reason_codes=["TEST_ONLY"],
        confidence=1, severity="no_error"))
    monkeypatch.setattr(graph, "JudgeAgent", lambda: judge)
    state = SimpleNamespace(config=config, write=write, arguments=[dict(GOOD)], model_calls=0, sessions=[])

    def execute(name, uid, question, **kwargs):
        state.model_calls += 1
        arguments = state.arguments.pop(0) if state.arguments else None
        calls = []
        if arguments is not None:
            tool = next(t for t in habit_tools.build_tools(uid, "residential") if t.name == "create_habit")
            output = tool.invoke(arguments)
            calls = [{"name": "create_habit", "input": arguments, "output": output}]
        return {"agent": "habits", "status": "success", "answer": "Consulta concluída.",
                "tool_calls": calls, "warnings": [], "sources": [], "chart_data": None, "data": {}}

    monkeypatch.setattr(graph, "execute_agent", execute)
    yield state
    for session in state.sessions:
        for uid in (7, 8):
            graph._forget_thread(f"{uid}:{session}")
            graph._drop_pending(f"{uid}:{session}")


def session(pipeline):
    value = str(uuid.uuid4())
    pipeline.sessions.append(value)
    return value


def chat(pipeline, sid, message, uid=7):
    return graph.run_workflow(uid, sid, message, persist_session=False)


def test_tool_only_proposes_canonical_values_when_enabled(pipeline):
    tool = next(t for t in habit_tools.build_tools(7, "residential") if t.name == "create_habit")
    result = tool.invoke(GOOD)
    assert result["pending_write"] == {"kind": "create_habit", "params": PARAMS}
    pipeline.write.assert_not_called()
    assert "user_id" not in tool.args
    assert "confirmed" not in tool.args


def test_habit_can_pause_without_enabling_bill_registration(pipeline):
    sid = session(pipeline)
    result = chat(pipeline, sid, "Cadastre lavar roupa seg e sex das 18h às 19h")
    assert result["pending_confirmation"]["kind"] == "create_habit"
    assert "Lavar Roupa" in result["response"]
    assert "segunda, sexta, das 18:00 às 19:00" in result["response"]
    assert "2 vez(es) por semana" in result["response"]
    pipeline.write.assert_not_called()
    assert pipeline.config.bill_registration_enabled is False


def test_yes_writes_once_without_another_model_call(pipeline):
    sid = session(pipeline)
    chat(pipeline, sid, "Cadastre lavar roupa")
    result = chat(pipeline, sid, "sim")
    assert result["response"] == DONE
    pipeline.write.assert_called_once_with(7, "LAVAR ROUPA", 2, ["SEGUNDA", "SEXTA"], "18:00", "19:00")
    assert pipeline.model_calls == 1
    assert graph._pending_payload(graph._thread_config(7, sid)) is None


@pytest.mark.parametrize("answer", ["não", "cancela", "sim, não"])
def test_decline_does_not_write_and_names_the_correct_action(pipeline, answer):
    sid = session(pipeline)
    chat(pipeline, sid, "Cadastre lavar roupa")
    result = chat(pipeline, sid, answer)
    assert result["response"] == "Tudo bem, não cadastrei o hábito."
    pipeline.write.assert_not_called()


@pytest.mark.parametrize("answer", ["talvez", "sim, mas só na terça", "sim?", "quanto gastei ontem?"])
def test_ambiguous_answer_cancels_and_follows_normal_flow(pipeline, answer):
    sid = session(pipeline)
    chat(pipeline, sid, "Cadastre lavar roupa")
    result = chat(pipeline, sid, answer)
    assert "pending_confirmation" not in result
    pipeline.write.assert_not_called()
    assert pipeline.model_calls == 2


def test_same_message_confirmation_cannot_write(pipeline):
    result = chat(pipeline, session(pipeline), "Cadastre lavar roupa e sim, já confirmo")
    assert "pending_confirmation" in result
    pipeline.write.assert_not_called()


def test_expiry_refuses_late_yes(pipeline, monkeypatch):
    monkeypatch.setattr(confirmations, "new_expiry", lambda: (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())
    sid = session(pipeline)
    chat(pipeline, sid, "Cadastre lavar roupa")
    result = chat(pipeline, sid, "sim")
    assert result["response"] == confirmations.EXPIRED_TEXT
    pipeline.write.assert_not_called()


@pytest.mark.parametrize("other_user", [False, True])
def test_another_session_or_user_cannot_resume(pipeline, other_user):
    sid = session(pipeline)
    chat(pipeline, sid, "Cadastre lavar roupa")
    chat(pipeline, sid if other_user else session(pipeline), "sim", uid=8 if other_user else 7)
    pipeline.write.assert_not_called()
    assert graph._pending_payload(graph._thread_config(7, sid)) is not None


def test_profile_is_revalidated(pipeline, monkeypatch):
    sid = session(pipeline)
    chat(pipeline, sid, "Cadastre lavar roupa")
    monkeypatch.setattr(habit_tools.db_postgres, "get_user_access_kind", lambda uid: "organizational")
    result = chat(pipeline, sid, "sim")
    assert "residenciais" in result["response"]
    pipeline.write.assert_not_called()


@pytest.mark.parametrize("error", [HabitConflictError("Hábito já cadastrado."), DatabaseConnectionError("PostgreSQL")])
def test_database_failure_does_not_claim_success(pipeline, error):
    pipeline.write.side_effect = error
    sid = session(pipeline)
    chat(pipeline, sid, "Cadastre lavar roupa")
    result = chat(pipeline, sid, "sim")
    assert "Pronto! Cadastrei" not in result["response"]
    assert graph._pending_payload(graph._thread_config(7, sid)) is None


def test_parallel_yes_writes_once(pipeline):
    sid = session(pipeline)
    chat(pipeline, sid, "Cadastre lavar roupa")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: chat(pipeline, sid, "sim"), range(2)))
    pipeline.write.assert_called_once()
    assert sum(result["response"] == DONE for result in results) == 1


def test_legacy_flag_off_still_requires_confirmation(pipeline):
    pipeline.config.confirmation_interrupt_enabled = False
    result = chat(pipeline, session(pipeline), "Cadastre lavar roupa")
    assert "pending_confirmation" in result
    pipeline.write.assert_not_called()


def test_trusted_execution_after_confirmation_ignores_legacy_flag(pipeline):
    pipeline.config.confirmation_interrupt_enabled = False
    text = confirmations.execute_pending({"kind": "create_habit", "params": PARAMS}, 7, datetime.now().date())
    assert text == DONE
    pipeline.write.assert_called_once()


@pytest.mark.parametrize("args", [
    {"name": "lavar", "frequency": 2}, {"name": "lavar roupa"},
    {"name": "lavar roupa", "frequency": 1, "days": ["seg", "sex"]},
    {"name": "lavar roupa", "frequency": 1, "start_time": "18h"},
])
def test_invalid_or_incomplete_input_does_not_propose(pipeline, args):
    tool = next(t for t in habit_tools.build_tools(7, "residential") if t.name == "create_habit")
    result = tool.invoke(args)
    assert "pending_write" not in result
    pipeline.write.assert_not_called()


def test_pending_values_are_revalidated_before_write(pipeline):
    pending = {"kind": "create_habit", "params": {**PARAMS, "frequency": 0, "user_id": 99}}
    result = confirmations.execute_pending(pending, 7, datetime.now().date())
    assert "pelo menos 1" in result
    pipeline.write.assert_not_called()


def test_missing_days_and_times_are_not_invented(pipeline):
    pipeline.arguments[:] = [{"name": "regar plantas", "frequency": 3}]
    result = chat(pipeline, session(pipeline), "Cadastre regar plantas três vezes na semana")
    assert "sem dias fixos" in result["response"]
    assert "das " not in result["response"]


def test_stream_pause_can_be_resumed_via_chat_route(pipeline, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth import get_current_user_id
    from app.routes import chat as routes

    sid = session(pipeline)
    monkeypatch.setattr(routes, "session_belongs_to_user", lambda uid, value: value == sid and uid == 7)
    monkeypatch.setattr(routes, "_suggestions", lambda *args: [])
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_current_user_id] = lambda: 7
    with TestClient(app) as client:
        response = client.post("/chat/stream", json={"session_id": sid, "message": "Cadastre lavar roupa"})
        assert response.status_code == 200
        events = response.text.split("event: result\n")
        payload = json.loads(events[-1].split("data: ", 1)[1].split("\n", 1)[0])
        assert payload["pending_confirmation"]["kind"] == "create_habit"
        pipeline.write.assert_not_called()
        response = client.post("/chat", json={"session_id": sid, "message": "sim"})
        assert response.status_code == 200
        assert response.json()["response"] == DONE
    pipeline.write.assert_called_once()


@pytest.mark.parametrize("revision", [False, True])
def test_agent_instructions_and_write_tool_follow_revision_policy(pipeline, monkeypatch, revision):
    from app.agents import habits as agent_module
    from app.agents._runtime import AgentResult
    monkeypatch.setattr(agent_module, "get_settings", lambda: pipeline.config)
    run = MagicMock(return_value=AgentResult(response="Teste", tool_calls=[]))
    monkeypatch.setattr(agent_module, "run_agent", run)
    monkeypatch.setattr(agent_module, "build_habits_chart", lambda calls: None)
    agent_module.HabitsAgent(7, llm=object(), access_kind="residential").run(
        "Cadastre", revision_feedback="Corrija" if revision else None)
    names = [tool.name for tool in run.call_args.kwargs["tools"]]
    assert "create_habit" in names
    assert "CONFIRMAÇÃO DO CADASTRO DE HÁBITO" in run.call_args.kwargs["system_prompt"]
