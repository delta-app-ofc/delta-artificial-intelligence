"""Unidades originais e julgamento antes de qualquer escrita, com dependências substituídas."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.agents.judge import JudgeResult
from app.graph import workflow as graph
from app.tools.forecast import tools
from tests.test_confirmation_interrupt import pipeline, chat, new_session, GOOD


@pytest.mark.parametrize("message, expected", [
    ("Registre R$ 150 e 1200 cm³", None),
    ("Registre R$ 150 e 1.200 litros", 1.2),
    ("Cadastre a conta de outubro de 2026: R$ 150,00 e consumo de 1.200 litros (não 1.200 m³).", 1.2),
    ("Consumo de 1.200 litros, e não 1.200 m³", 1.2),
    ("Consumo de 1.200 litros (NAO 1.200 m3)", 1.2),
    ("Não 1.200 m³; consumo de 1.200 litros", 1.2),
    ("Consumo de 1.200 litros, não 1.200 cm³", 1.2),
    ("Não 1.200 litros", None),
    ("Consumo de 1.200 litros e 1.200 m³", None),
    ("Registre R$ 150 e 7.500 mililitros", None),
    ("Registre R$ 150 e 250 galões americanos", None),
    ("Registre R$ 150 e 12.000 litros, equivalentes a 12 m³", 12.0),
    ("Registre R$ 150 e 12 m³ ou 18 m³", None),
    ("Registre R$ 150 e 1200", None),
    ("Registre R$ 150 e -12 m³", None),
    ("Registre R$ 150 e 1 200 litros", None),
    ("Registre R$ 150 e 1/2 m³", None),
])
def test_original_units_override_model_and_never_write(monkeypatch, message, expected):
    monkeypatch.setattr(tools, "get_settings", lambda: SimpleNamespace(bill_registration_enabled=True))
    write = MagicMock()
    monkeypatch.setattr(tools.db_postgres, "register_last_water_bill", write)
    register = next(t for t in tools.build_tools(7, date(2026,11,6), "residential", source_question=message)
                    if t.name == "register_last_bill")
    result = register.invoke({"month": "2026-10", "total_value": 150, "m3_value": 1200, "confirmed": True})
    write.assert_not_called()
    if expected is None:
        assert result["status"] == "error"
    else:
        assert result["pending_write"]["params"]["m3_value"] == expected
        assert result["pending_write"]["source_consumption"]


@pytest.mark.parametrize("decision,status", [("reject", "evaluated"), ("reject", "unavailable"), ("approve", "unavailable")])
def test_judge_blocks_before_confirmation_or_write(pipeline, monkeypatch, decision, status):
    def review(payload, **kwargs):
        assert payload.context["pending_write"]["params"]["m3_value"] == 9.8
        pipeline.write.assert_not_called()
        return JudgeResult(decision=decision, status=status, justification="teste", reason_codes=[],
                           confidence=1, severity="critical_error")
    monkeypatch.setattr(graph, "JudgeAgent", lambda: SimpleNamespace(run=review))
    result = chat(pipeline, new_session(), "Registre R$ 142,30 e 9,8 m³ em junho de 2025")
    assert "pending_confirmation" not in result
    pipeline.write.assert_not_called()
    assert pipeline.saved_turns == []


def test_judge_exception_never_reaches_confirmation(pipeline, monkeypatch):
    monkeypatch.setattr(graph, "JudgeAgent", lambda: SimpleNamespace(
        run=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline"))))
    result = chat(pipeline, new_session(), "Registre 9,8 m³")
    assert "pending_confirmation" not in result
    pipeline.write.assert_not_called()


def test_only_final_revised_proposal_is_confirmed_and_written(pipeline, monkeypatch):
    decisions = iter(["correct", "approve"])
    def review(payload, **kwargs):
        return JudgeResult(decision=next(decisions), status="evaluated", justification="corrija total",
                           reason_codes=[], confidence=1, severity="correctable_error")
    monkeypatch.setattr(graph, "JudgeAgent", lambda: SimpleNamespace(run=review))
    pipeline.tool_args[:] = [GOOD, GOOD | {"total_value": 100}]
    sid = new_session()
    result = chat(pipeline, sid, "Registre R$ 100 e 9,8 m³")
    assert "R$ 100,00" in result["response"]
    pipeline.write.assert_not_called()
    chat(pipeline, sid, "sim")
    pipeline.write.assert_called_once()
    assert pipeline.write.call_args.args[2] == 100


def test_changed_proposal_cannot_reach_interrupt(monkeypatch):
    monkeypatch.setattr(graph, "interrupt", lambda *a: pytest.fail("ação modificada não pode pausar"))
    result = graph._confirm_node({"pending_write": {"kind": "create_habit", "params": {}},
                                 "approved_write": None, "judge_action": "approve", "output_approved": True})
    assert result["pending_write"] is None


def test_output_rejected_after_judge_never_reaches_confirmation(pipeline, monkeypatch):
    monkeypatch.setattr(graph, "validate_output", lambda *a, **k: {"ok": False, "reason": "teste"})
    result = chat(pipeline, new_session(), "Registre 9,8 m³")
    assert "pending_confirmation" not in result
    pipeline.write.assert_not_called()
    assert pipeline.saved_turns == []


def test_playground_keeps_checkpoint_session_id_while_waiting(monkeypatch):
    from app.routes import playground
    sid = "sessao-local"
    monkeypatch.setattr(playground, "validate_input_rules", lambda *a: {
        "ok": True, "message": "registre", "pii_map": {}})
    monkeypatch.setattr(playground, "validate_output", lambda text, **k: {"ok": True, "response": text})
    monkeypatch.setattr(playground, "create_session", lambda *a: pytest.fail("não pode trocar a sessão pausada"))
    monkeypatch.setattr(playground, "append_turn", lambda *a: pytest.fail("proposta já está no checkpoint"))
    result = playground.run_test(playground.PlaygroundRequest(message="registre", session_id=sid), "chat",
        workflow_runner=lambda *a, **k: {"response": "Confirma o cadastro?", "judge_action": "approve",
            "output_approved": True, "pending_confirmation": {"kind": "create_habit"}})
    assert result["session_id"] == sid
