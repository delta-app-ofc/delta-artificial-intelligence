"""Regressões para garantir que ações só persistam depois da aprovação."""

import pytest

from app.agents.judge import JudgeResult, SAFE_RESPONSE
from app.graph import workflow
from app.tools.exceptions import DatabaseAccessError


ACTION = {
    "type": "create_habit",
    "name": "LAVAR ROUPA",
    "frequency": 3,
    "days": ["SEGUNDA"],
    "start_time": "18:00",
    "end_time": "19:00",
}


def _state():
    return {
        "user_id": 7,
        "access_kind": "residential",
        "question": "Cadastre lavar roupa três vezes por semana.",
        "candidate": "Preparei o cadastro; aguarde validação.",
        "response": "Preparei o cadastro; aguarde validação.",
        "agent_results": [],
        "chart_data": None,
        "pending_actions": [ACTION.copy()],
        "approved_actions": [],
        "judge_history": [],
        "revision_count": 0,
        "judge_action": "",
        "judge_status": "",
        "output_approved": False,
        "_persist_session": False,
        "pii_map": {},
        "_blocked": False,
    }


def _judge_result(decision="approve", status="evaluated"):
    return JudgeResult(
        decision=decision,
        status=status,
        justification="Revisão sintética.",
        reason_codes=[],
        confidence=1.0,
        severity="no_error",
    )


def test_judge_sees_pending_action_and_database_runs_after_output_guard(monkeypatch):
    events = []
    captured = {}

    def review(self, judge_input, **kwargs):
        events.append("judge")
        captured.update(judge_input.model_dump())
        return _judge_result()

    def output_guard(text, pii_map):
        events.append("output_guard")
        return {"ok": True, "response": text}

    def save(*args):
        events.append("database")
        return {"habit_id": 41, "name": args[1], "frequency": args[2]}

    monkeypatch.setattr(workflow.JudgeAgent, "run", review)
    monkeypatch.setattr(workflow, "validate_output", output_guard)
    monkeypatch.setattr(workflow, "validate_ownership", lambda *args: {"ok": True})
    monkeypatch.setattr(workflow.db_postgres, "create_habit", save)

    state = _state()
    state.update(workflow._judge_node(state))
    state.update(workflow._publish_node(state))
    state.update(workflow._guardrail_output_node(state))
    state.update(workflow._persist_approved_node(state))

    assert captured["context"]["pending_actions"] == [ACTION]
    assert events == ["judge", "output_guard", "database"]
    assert state["response"] == "Hábito LAVAR ROUPA cadastrado para 3 vez(es) por semana."


@pytest.mark.parametrize(("decision", "status"), [
    ("reject", "evaluated"),
    ("reject", "unavailable"),
    ("correct", "evaluated"),
])
def test_blocked_or_unavailable_judge_never_writes_or_saves_turn(monkeypatch, decision, status):
    writes, saved_turns = [], []
    monkeypatch.setattr(workflow.JudgeAgent, "run", lambda *a, **k: _judge_result(decision, status))
    monkeypatch.setattr(workflow.db_postgres, "create_habit", lambda *a: writes.append(a))
    monkeypatch.setattr(workflow, "append_turn", lambda *a: saved_turns.append(a))

    state = _state()
    state.update(workflow._judge_node(state))
    state.update(workflow._block_node(state))
    state.update(workflow._guardrail_output_node(state))
    state.update(workflow._persist_approved_node(state))

    assert writes == []
    assert saved_turns == []
    assert state["response"] == SAFE_RESPONSE


def test_output_guard_rejection_never_writes(monkeypatch):
    writes = []
    monkeypatch.setattr(workflow.db_postgres, "create_habit", lambda *a: writes.append(a))
    state = _state() | {
        "judge_action": "approve",
        "judge_status": "evaluated",
        "approved_actions": [ACTION.copy()],
    }
    monkeypatch.setattr(workflow, "validate_output", lambda *a: {"ok": False, "reason": "rejeitada"})

    state.update(workflow._guardrail_output_node(state))
    state.update(workflow._persist_approved_node(state))

    assert writes == []
    assert state["output_approved"] is False


def test_malformed_or_multiple_actions_fail_closed(monkeypatch):
    writes = []
    monkeypatch.setattr(workflow.db_postgres, "create_habit", lambda *a: writes.append(a))
    state = _state() | {
        "judge_action": "approve",
        "judge_status": "evaluated",
        "output_approved": True,
        "approved_actions": [ACTION.copy(), ACTION.copy()],
    }

    result = workflow._persist_approved_node(state)

    assert writes == []
    assert result["response"] == SAFE_RESPONSE


def test_corrected_action_replaces_first_proposal_and_is_written_once(monkeypatch):
    revised_action = ACTION | {"name": "REGAR PLANTAS", "days": ["TERÇA"]}
    results = iter([_judge_result("correct"), _judge_result("approve")])
    writes = []
    monkeypatch.setattr(workflow.JudgeAgent, "run", lambda *a, **k: next(results))
    monkeypatch.setattr(
        workflow.db_postgres, "create_habit",
        lambda *args: writes.append(args) or {"name": args[1], "frequency": args[2]},
    )
    monkeypatch.setattr(workflow, "validate_output", lambda text, pii_map: {"ok": True, "response": text})
    monkeypatch.setattr(workflow, "validate_ownership", lambda *args: {"ok": True})

    state = _state()
    state.update(workflow._judge_node(state))
    assert state["judge_action"] == "correct"
    state.update(workflow._prepare_revision_node(state))
    assert state["pending_actions"] == []
    assert state["approved_actions"] == []

    state.update({
        "pending_actions": [revised_action],
        "candidate": "Preparei regar plantas para 3 vezes por semana.",
        "response": "Preparei regar plantas para 3 vezes por semana.",
    })
    state.update(workflow._judge_node(state))
    state.update(workflow._publish_node(state))
    state.update(workflow._guardrail_output_node(state))
    state.update(workflow._persist_approved_node(state))

    assert writes == [(7, "REGAR PLANTAS", 3, ["TERÇA"], "18:00", "19:00")]


def test_action_changed_after_approval_is_not_written(monkeypatch):
    writes = []
    monkeypatch.setattr(workflow.JudgeAgent, "run", lambda *a, **k: _judge_result())
    monkeypatch.setattr(workflow.db_postgres, "create_habit", lambda *a: writes.append(a))
    state = _state()
    state.update(workflow._judge_node(state))
    state["pending_actions"][0]["days"].append("TERÇA")
    state.update({"judge_action": "approve", "judge_status": "evaluated", "output_approved": True})

    result = workflow._persist_approved_node(state)

    assert writes == []
    assert result["response"] == SAFE_RESPONSE


def test_database_error_never_returns_success_or_retries(monkeypatch):
    writes = []

    def fail_once(*args):
        writes.append(args)
        raise DatabaseAccessError("falha SQL")

    monkeypatch.setattr(workflow.db_postgres, "create_habit", fail_once)
    state = _state() | {
        "judge_action": "approve",
        "judge_status": "evaluated",
        "approved_actions": [ACTION.copy()],
        "output_approved": True,
    }
    monkeypatch.setattr(workflow, "append_turn", lambda *args: pytest.fail("histórico desligado"))

    result = workflow._persist_approved_node(state)

    assert len(writes) == 1
    assert "cadastrado" not in result["response"].lower()
    assert "Confira os hábitos" in result["response"]


def test_isolated_playground_only_reports_pending_action(monkeypatch):
    from app.routes import playground

    monkeypatch.setattr(
        playground, "validate_input",
        lambda user_id, message: {"ok": True, "message": message, "pii_map": {}},
    )
    monkeypatch.setattr(
        playground, "execute_agent",
        lambda *args, **kwargs: {
            "agent": "habits", "status": "success", "answer": "O hábito foi cadastrado.",
            "tool_calls": [{"name": "create_habit", "output": {"status": "pending_approval"}}],
        },
    )
    monkeypatch.setattr(playground, "validate_output", lambda text, pii_map: {"ok": True, "response": text})
    monkeypatch.setattr(playground, "append_turn", lambda *args: pytest.fail("aba isolada não salva turnos"))
    monkeypatch.setattr(workflow.db_postgres, "create_habit", lambda *args: pytest.fail("aba isolada não grava"))

    response = playground.run_test(playground.PlaygroundRequest(message="Cadastre lavar roupa"), "habits")

    assert response["response"] == (
        "O cadastro foi preparado, mas só pode ser concluído pelo chat principal após a validação."
    )
