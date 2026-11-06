"""Pausa com interrupt() antes de gravar: grafo real, com modelo, banco e juiz substituídos."""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.agents.judge import JudgeResult
from app.graph import confirmations
from app.graph import workflow as graph
from app.graph.router import RoutingDecision
from app.schemas import ChatResponse
from app.tools.exceptions import DatabaseConnectionError, LastWaterBillConflictError
from app.tools.forecast import tools as forecast_tools

TODAY = date(2026, 11, 2)
GOOD = {"month": "2025-06", "total_value": 142.3, "m3_value": 9.8}
SAVED = {"bill_id": 5, "month": date(2025, 6, 1), "total_value": Decimal("142.30"), "m3_value": Decimal("9.80")}
PAUSE_TEXT = (
    "Confirma o registro da conta de junho de 2025: R$ 142,30 e 9,8 m³ (informado: 9,8 m³)? "
    "Responda sim para salvar ou não para cancelar."
)
DONE_TEXT = "Pronto! Registrei a conta de junho de 2025: R$ 142,30 e 9,8 m³."


@pytest.fixture
def pipeline(monkeypatch):
    config = SimpleNamespace(confirmation_interrupt_enabled=True, bill_registration_enabled=True)
    monkeypatch.setattr(graph, "get_settings", lambda: config)
    monkeypatch.setattr(confirmations, "get_settings", lambda: config)
    monkeypatch.setattr(forecast_tools, "get_settings", lambda: config)

    write = MagicMock(return_value=SAVED)
    monkeypatch.setattr(forecast_tools.db_postgres, "register_last_water_bill", write)
    monkeypatch.setattr(forecast_tools.db_postgres, "get_user_access_kind", lambda user_id: "residential")

    monkeypatch.setattr(graph, "classify_input", lambda question: None)
    monkeypatch.setattr(graph, "load_history_validated", lambda *args: [])
    monkeypatch.setattr(graph, "build_context", lambda *args: {"recent_messages": [], "relevant_memory": []})
    monkeypatch.setattr(graph, "resolve_access_kind", lambda user_id: "residential")
    monkeypatch.setattr(
        graph, "classify",
        lambda question, context: RoutingDecision(intent="forecast", complexity="simple", agents=["forecast"]),
    )

    class Judge:
        def run(self, state, **kwargs):
            return JudgeResult(decision="approve", status="evaluated", justification="ok",
                               reason_codes=["TEST_ONLY"], confidence=1, severity="no_error")
    monkeypatch.setattr(graph, "JudgeAgent", Judge)

    saved_turns = []
    monkeypatch.setattr(graph, "append_turn", lambda *args: saved_turns.append(args))
    monkeypatch.setattr(graph, "refresh_session_meta", lambda *args: None)

    state = SimpleNamespace(config=config, write=write, saved_turns=saved_turns,
                            agent_calls=[], tool_args=[GOOD], sessions=[])

    def fake_execute_agent(name, user_id, question, **kwargs):
        """Roda a ferramenta de verdade; o texto do 'modelo' é descartado quando há pausa."""
        state.agent_calls.append(question)
        args = state.tool_args.pop(0) if state.tool_args else None
        if args is None:
            return {"agent": name, "status": "success", "answer": "A estimativa é R$ 100,00.",
                    "sources": [], "chart_data": None, "tool_calls": [], "warnings": [], "data": {}}
        tools = {t.name: t for t in forecast_tools.build_tools(user_id, TODAY, "residential", source_question="9,8 m³")}
        output = tools["register_last_bill"].invoke(args)
        return {"agent": name, "status": "success", "answer": "Pode salvar? (texto do modelo)",
                "sources": [], "chart_data": None, "warnings": [], "data": {},
                "tool_calls": [{"name": "register_last_bill", "input": args, "output": output}]}
    monkeypatch.setattr(graph, "execute_agent", fake_execute_agent)

    graph._PENDING.clear()
    yield state
    for session_id in state.sessions:
        for user in (7, 8):
            graph._forget_thread(f"{user}:{session_id}")
    graph._PENDING.clear()


def chat(state, session_id, message, user_id=7):
    if session_id not in state.sessions:
        state.sessions.append(session_id)
    return graph.run_workflow(user_id, session_id, message)


def new_session():
    return str(uuid.uuid4())


def pending_of(session_id, user_id=7):
    return graph._pending_payload(graph._thread_config(user_id, session_id))


class TestPauseAndResume:
    def test_first_message_pauses_and_writes_nothing(self, pipeline):
        session = new_session()
        result = chat(pipeline, session, "Quero registrar minha conta de junho de 2025")
        assert result["response"] == PAUSE_TEXT
        assert result["pending_confirmation"]["kind"] == "register_last_bill"
        assert result["pending_confirmation"]["summary"] == PAUSE_TEXT
        pipeline.write.assert_not_called()
        assert pending_of(session) is not None
        assert [turn[2:] for turn in pipeline.saved_turns] == [
            ("human", "Quero registrar minha conta de junho de 2025"), ("assistant", PAUSE_TEXT)]

    def test_yes_writes_once_with_the_trusted_user_and_does_not_call_the_model_again(self, pipeline):
        session = new_session()
        chat(pipeline, session, "Registre minha conta")
        result = chat(pipeline, session, "sim, pode salvar")
        assert result["response"] == DONE_TEXT
        pipeline.write.assert_called_once_with(7, date(2025, 6, 1), Decimal("142.30"), Decimal("9.80"))
        assert len(pipeline.agent_calls) == 1
        assert pending_of(session) is None
        assert pipeline.saved_turns[-2][2:] == ("human", "sim, pode salvar")
        assert pipeline.saved_turns[-1][2:] == ("assistant", DONE_TEXT)

    def test_no_cancels_without_writing(self, pipeline):
        session = new_session()
        chat(pipeline, session, "Registre minha conta")
        result = chat(pipeline, session, "não")
        assert result["response"] == confirmations.DECLINED_TEXT
        pipeline.write.assert_not_called()
        assert pending_of(session) is None

    def test_the_model_cannot_bypass_the_pause_with_confirmed_true(self, pipeline):
        pipeline.tool_args[:] = [{**GOOD, "confirmed": True}]
        session = new_session()
        result = chat(pipeline, session, "Registre e já confirmo")
        assert result["response"] == PAUSE_TEXT
        pipeline.write.assert_not_called()

    def test_a_yes_in_the_same_message_does_not_count(self, pipeline):
        session = new_session()
        result = chat(pipeline, session, "Sim, pode registrar a conta de junho de 2025: R$ 142,30 e 9,8 m³")
        assert "pending_confirmation" in result
        pipeline.write.assert_not_called()


class TestOtherMessagesCancelThePending:
    @pytest.mark.parametrize("message", ["sim, mas o valor é 150", "quanto gastei ontem?", "pode ser outro valor",
                                         "talvez"])
    def test_anything_but_a_clear_answer_never_writes(self, pipeline, message):
        pipeline.tool_args[:] = [GOOD, None]
        session = new_session()
        chat(pipeline, session, "Registre minha conta")
        result = chat(pipeline, session, message)
        pipeline.write.assert_not_called()
        assert pending_of(session) is None
        assert result["response"] != DONE_TEXT
        assert len(pipeline.agent_calls) == 2  # a mensagem seguiu o fluxo normal

    def test_a_new_question_is_answered_normally_after_the_pending_is_dropped(self, pipeline):
        pipeline.tool_args[:] = [GOOD, None]
        session = new_session()
        chat(pipeline, session, "Registre minha conta")
        result = chat(pipeline, session, "Quanto vou pagar mês que vem?")
        assert "A estimativa é R$ 100,00." in result["response"]
        assert "pending_confirmation" not in result
        assert pending_of(session) is None


class TestExpiryAndOwnership:
    def test_late_yes_expires_without_writing(self, pipeline, monkeypatch):
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        monkeypatch.setattr(confirmations, "new_expiry", lambda now=None: past)
        session = new_session()
        chat(pipeline, session, "Registre minha conta")
        result = chat(pipeline, session, "sim")
        assert result["response"] == confirmations.EXPIRED_TEXT
        pipeline.write.assert_not_called()
        assert pending_of(session) is None

    def test_late_unrelated_message_goes_to_the_normal_flow(self, pipeline, monkeypatch):
        pipeline.tool_args[:] = [GOOD, None]
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        monkeypatch.setattr(confirmations, "new_expiry", lambda now=None: past)
        session = new_session()
        chat(pipeline, session, "Registre minha conta")
        result = chat(pipeline, session, "Quanto vou pagar mês que vem?")
        assert "A estimativa é R$ 100,00." in result["response"]
        pipeline.write.assert_not_called()

    def test_purge_forgets_expired_pendings_only(self, pipeline):
        session = new_session()
        chat(pipeline, session, "Registre minha conta")
        thread = f"7:{session}"
        graph._PENDING[thread] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        graph._purge_expired_pending()
        assert thread not in graph._PENDING
        assert pending_of(session) is None

    def test_another_user_cannot_resume_the_pending(self, pipeline):
        pipeline.tool_args[:] = [GOOD, None]
        session = new_session()
        chat(pipeline, session, "Registre minha conta", user_id=7)
        result = chat(pipeline, session, "sim", user_id=8)
        pipeline.write.assert_not_called()
        assert result["response"] != DONE_TEXT
        assert pending_of(session, user_id=7) is not None


class TestWriteFailures:
    def test_existing_month_is_reported_and_not_overwritten(self, pipeline):
        pipeline.write.side_effect = LastWaterBillConflictError("x")
        session = new_session()
        chat(pipeline, session, "Registre minha conta")
        result = chat(pipeline, session, "sim")
        assert "Já existe uma conta registrada" in result["response"]
        assert DONE_TEXT not in result["response"]

    def test_database_outage_is_not_success(self, pipeline):
        pipeline.write.side_effect = DatabaseConnectionError("PostgreSQL")
        session = new_session()
        chat(pipeline, session, "Registre minha conta")
        result = chat(pipeline, session, "sim")
        assert "Nada foi registrado" in result["response"]

    def test_profile_is_checked_again_at_commit(self, pipeline, monkeypatch):
        session = new_session()
        chat(pipeline, session, "Registre minha conta")
        monkeypatch.setattr(forecast_tools.db_postgres, "get_user_access_kind", lambda user_id: "organizational")
        result = chat(pipeline, session, "sim")
        pipeline.write.assert_not_called()
        assert "residenciais" in result["response"]


class TestFlagOff:
    def test_without_the_flag_nothing_pauses(self, pipeline):
        pipeline.config.confirmation_interrupt_enabled = False
        session = new_session()
        result = chat(pipeline, session, "Registre minha conta")
        assert "pending_confirmation" in result
        pipeline.write.assert_not_called()
        assert pending_of(session) is not None


class TestStreaming:
    def _events(self, session, message, user_id=7):
        return list(graph.run_workflow_events(user_id, session, message))

    def test_pause_and_resume_through_the_stream(self, pipeline):
        session = new_session()
        pipeline.sessions.append(session)
        final = [e for e in self._events(session, "Registre minha conta") if e["type"] == "final"][0]
        assert final["state"]["response"] == PAUSE_TEXT
        assert final["state"]["pending_confirmation"]["kind"] == "register_last_bill"
        pipeline.write.assert_not_called()
        assert pending_of(session) is not None
        final = [e for e in self._events(session, "sim") if e["type"] == "final"][0]
        assert final["state"]["response"] == DONE_TEXT
        pipeline.write.assert_called_once()
        assert pending_of(session) is None


class TestAnswerParsing:
    @pytest.mark.parametrize("text", ["sim", "Sim!", "SIM, pode salvar", "pode registrar", "confirmo", "ok",
                                      "isso mesmo", "claro", "sim por favor"])
    def test_clear_yes(self, text):
        assert confirmations.parse_answer(text) is True

    @pytest.mark.parametrize("text", ["não", "nao", "Não quero", "cancela", "desisto", "negativo",
                                      "sim, não", "esquece"])
    def test_clear_no(self, text):
        assert confirmations.parse_answer(text) is False

    @pytest.mark.parametrize("text", ["", "   ", "talvez", "pode ser outro valor", "sim, mas o valor é 150",
                                      "sim 150", "posso salvar?", "quanto gastei ontem", "sim pode salvar a conta",
                                      "ok " * 7])
    def test_everything_else_is_not_an_answer(self, text):
        assert confirmations.parse_answer(text) is None


def test_chat_response_schema_accepts_and_defaults_the_pending_field():
    base = {"response": "x", "session_id": "s"}
    assert ChatResponse(**base).pending_confirmation is None
    pending = {"kind": "register_last_bill", "summary": "Confirma?", "expires_at": "2026-11-02T10:00:00+00:00"}
    assert ChatResponse(**base, pending_confirmation=pending).pending_confirmation.kind == "register_last_bill"


@pytest.mark.parametrize("expires_at", [None, "invalid", "2026-11-02T10:00:00", 123])
def test_invalid_or_timezone_free_expiry_is_expired(expires_at):
    assert confirmations.is_expired(expires_at)


def test_disabling_registration_after_proposal_prevents_write(pipeline):
    session = new_session()
    chat(pipeline, session, "Registre minha conta")
    pipeline.config.bill_registration_enabled = False
    result = chat(pipeline, session, "sim")
    pipeline.write.assert_not_called()
    assert "desativado" in result["response"]


@pytest.mark.parametrize("streaming", [False, True])
def test_parallel_confirmations_write_only_once_and_release_the_session_lock(pipeline, streaming):
    from concurrent.futures import ThreadPoolExecutor
    session = new_session()
    chat(pipeline, session, "Registre minha conta")
    def answer(index):
        if streaming and index == 0:
            events = list(graph.run_workflow_events(7, session, "sim"))
            return next(event["state"] for event in events if event["type"] == "final")
        return chat(pipeline, session, "sim")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(answer, range(2)))
    pipeline.write.assert_called_once()
    assert sum(result["response"] == DONE_TEXT for result in results) == 1
    assert (7, session) not in confirmations._SESSION_LOCKS


def test_lock_is_removed_after_failure():
    with pytest.raises(RuntimeError):
        with confirmations.session_lock(7, "failure-test"):
            raise RuntimeError("test")
    assert (7, "failure-test") not in confirmations._SESSION_LOCKS


def test_a_different_session_cannot_confirm_another_session(pipeline):
    pipeline.tool_args[:] = [GOOD, None]
    first, second = new_session(), new_session()
    chat(pipeline, first, "Registre minha conta")
    chat(pipeline, second, "sim")
    pipeline.write.assert_not_called()
    assert pending_of(first) is not None


def test_new_process_without_checkpoint_cannot_confirm(pipeline):
    pipeline.tool_args[:] = [GOOD, None]
    session = new_session()
    chat(pipeline, session, "Registre minha conta")
    graph._forget_thread(f"7:{session}")
    graph._PENDING.clear()
    result = chat(pipeline, session, "sim")
    pipeline.write.assert_not_called()
    assert result["response"] != DONE_TEXT
