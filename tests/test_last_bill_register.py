"""Testa o cadastro da última conta (register_last_bill) sem banco nem LLM reais."""

import unittest
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import psycopg2.errors
from langchain_core.messages import AIMessage

from app.agents.forecast import ForecastAgent
from app.graph import router
from app.config import get_settings
from app.data import db_postgres
from app.tools.exceptions import DatabaseConnectionError, LastWaterBillConflictError
from app.tools.forecast import tools as forecast_tools

TODAY = date(2026, 11, 2)


def _tools(enabled=True, access_kind="residential", source="8,4 m³"):
    with patch.object(forecast_tools, "get_settings") as settings:
        settings.return_value.bill_registration_enabled = enabled
        return {t.name: t for t in forecast_tools.build_tools(7, TODAY, access_kind, source_question=source)}


def _register(args, access_kind="residential", **db):
    db.setdefault("return_value", {"bill_id": 5, "month": date(2026, 10, 1),
                                   "total_value": Decimal("120.50"), "m3_value": Decimal("8.40")})
    with patch.object(forecast_tools.db_postgres, "register_last_water_bill", **db) as write:
        return _tools(access_kind=access_kind, source=str(args["m3_value"]).replace(".", ",") + " m³")["register_last_bill"].invoke(args), write


GOOD = {"month": "2026-10", "total_value": 120.5, "m3_value": 8.4}


class FlagTest(unittest.TestCase):
    def test_tool_is_absent_by_default_and_present_when_enabled(self):
        self.assertFalse(get_settings().bill_registration_enabled)
        self.assertNotIn("register_last_bill", _tools(enabled=False))
        self.assertIn("register_last_bill", _tools(enabled=True))

    def test_disabled_keeps_the_original_ten_tools(self):
        self.assertEqual(len(_tools(enabled=False)), 10)

    def test_user_id_is_not_exposed(self):
        schema = _tools()["register_last_bill"].args
        self.assertEqual(set(schema), {"month", "total_value", "m3_value", "confirmed"})


class ProposeThenSaveTest(unittest.TestCase):
    def test_default_call_only_proposes_and_never_writes(self):
        out, write = _register(GOOD)
        self.assertEqual(out["status"], "pending_confirmation")
        self.assertEqual(out["pending_write"]["params"], {"month": "2026-10-01", "total_value": 120.5, "m3_value": 8.4})
        write.assert_not_called()

    def test_explicit_false_also_does_not_write(self):
        out, write = _register({**GOOD, "confirmed": False})
        self.assertEqual(out["status"], "pending_confirmation")
        write.assert_not_called()

    def test_confirmed_true_still_only_proposes(self):
        out, write = _register({**GOOD, "confirmed": True})
        self.assertEqual(out["status"], "pending_confirmation")
        write.assert_not_called()

    def test_write_helper_translates_database_failures(self):
        for error, status in [(LastWaterBillConflictError("x"), "conflict"),
                              (DatabaseConnectionError("PostgreSQL"), "error"),
                              (ValueError("recusado"), "error")]:
            with patch.object(forecast_tools.db_postgres, "register_last_water_bill", side_effect=error):
                result = forecast_tools.write_last_bill(7, date(2026,10,1), Decimal("120"), Decimal("8"))
                self.assertEqual(result["status"], status)


class ValidationTest(unittest.TestCase):
    def _error(self, **changes):
        out, write = _register({**GOOD, "confirmed": True, **changes})
        self.assertEqual(out["status"], "error", changes)
        write.assert_not_called()

    def test_invalid_or_future_month(self):
        for month in ("outubro", "2026-13", "10/2026", "", "2026-12"):
            with self.subTest(month=month):
                self._error(month=month)

    def test_current_month_is_accepted(self):
        out, _ = _register({**GOOD, "month": "2026-11"})
        self.assertEqual(out["status"], "pending_confirmation")

    def test_negative_nan_and_implausible_values(self):
        self._error(total_value=-1)
        self._error(m3_value=float("nan"))
        self._error(total_value=float("inf"))
        self._error(total_value=1_000_000)
        self._error(m3_value=99_999)

    def test_zero_is_a_valid_value(self):
        out, _ = _register({**GOOD, "total_value": 0, "m3_value": 0})
        self.assertEqual(out["status"], "pending_confirmation")

    def test_organization_account_cannot_register(self):
        out, write = _register({**GOOD, "confirmed": True}, access_kind="organizational")
        self.assertEqual(out["status"], "not_available")
        write.assert_not_called()


def _fake_cursor(execute_error=None, row=(5,)):
    cur = MagicMock()
    cur.execute.side_effect = execute_error
    cur.fetchone.return_value = row

    @contextmanager
    def fake(*args, **kwargs):
        yield cur

    return patch.object(db_postgres, "_cursor", fake), cur


class FakeCheckViolation(psycopg2.errors.CheckViolation):
    def __init__(self, message):
        super().__init__(message)
        self._message = message

    @property
    def diag(self):
        return MagicMock(message_primary=self._message)


class DatabaseLayerTest(unittest.TestCase):
    def test_inserts_without_overwriting_and_returns_the_id(self):
        ctx, cur = _fake_cursor()
        with ctx:
            out = db_postgres.register_last_water_bill(7, date(2026, 10, 1), Decimal("120.50"), Decimal("8.4"))
        sql = cur.execute.call_args.args[0]
        self.assertIn("INSERT INTO tb_last_water_bill", sql)
        self.assertIn("ON CONFLICT (user_id, month) DO NOTHING", sql)
        self.assertEqual(cur.execute.call_args.args[1][0], 7)
        self.assertEqual(out["bill_id"], 5)

    def test_existing_month_becomes_conflict_error(self):
        ctx, _ = _fake_cursor(row=None)
        with ctx, self.assertRaises(LastWaterBillConflictError):
            db_postgres.register_last_water_bill(7, date(2026, 10, 1), Decimal("1"), Decimal("1"))

    def test_python_guards_run_before_any_sql(self):
        ctx, cur = _fake_cursor()
        with ctx:
            with self.assertRaises(ValueError):
                db_postgres.register_last_water_bill(7, date(2026, 10, 15), Decimal("1"), Decimal("1"))
            with self.assertRaises(ValueError):
                db_postgres.register_last_water_bill(7, date(2026, 10, 1), Decimal("-1"), Decimal("1"))
        cur.execute.assert_not_called()

    def test_check_violation_becomes_generic_value_error(self):
        ctx, _ = _fake_cursor(FakeCheckViolation("detalhe interno chk_tb_last_water_bill_month"))
        with ctx, self.assertRaises(ValueError) as caught:
            db_postgres.register_last_water_bill(7, date(2026, 10, 1), Decimal("1"), Decimal("1"))
        self.assertNotIn("chk_tb_last_water_bill", str(caught.exception))


class AgentWiringTest(unittest.TestCase):
    def _run(self, enabled=True, **kwargs):
        with (
            patch.object(forecast_tools, "get_settings") as settings,
            patch("app.agents.forecast.run_agent") as run,
            patch("app.agents.forecast.build_simulation_chart", return_value=None),
            patch("app.agents.forecast.build_forecast_chart", return_value=None),
        ):
            settings.return_value.bill_registration_enabled = enabled
            run.return_value = MagicMock()
            ForecastAgent(7, llm=object(), today=TODAY, access_kind="residential").run("registre", **kwargs)
        call = run.call_args.kwargs
        return [t.name for t in call["tools"]], call["system_prompt"]

    def test_first_pass_has_the_tool_and_the_instructions(self):
        names, prompt = self._run()
        self.assertIn("register_last_bill", names)
        self.assertIn("CADASTRO DA ÚLTIMA CONTA", prompt)

    def test_revision_keeps_the_preparation_tool_and_instructions(self):
        for kwargs in ({"revision_feedback": "corrija"}, {"revision_context": {"previous_candidate": "x"}}):
            names, prompt = self._run(**kwargs)
            self.assertIn("register_last_bill", names)
            self.assertIn("get_last_bill", names)
            self.assertIn("CADASTRO DA ÚLTIMA CONTA", prompt)

    def test_disabled_flag_changes_nothing(self):
        names, prompt = self._run(enabled=False)
        self.assertNotIn("register_last_bill", names)
        self.assertNotIn("CADASTRO DA ÚLTIMA CONTA", prompt)


class RouterHintTest(unittest.TestCase):
    def _classify(self, enabled, access_kind="residential"):
        seen = []

        class FakeLLM:
            def invoke(self, messages):
                seen.append(messages)
                return AIMessage(content='{"intent": "bill_registration", "complexity": "simple", "agents": ["forecast"]}')

        with (
            patch("app.graph.router.get_settings") as settings,
            patch("app.services.llms.llm_rapido", FakeLLM()),
        ):
            settings.return_value.bill_registration_enabled = enabled
            decision = router.classify("registre minha conta", {"access_kind": access_kind, "recent_messages": []})
        return seen[0][0].content, decision

    def test_hint_routes_registration_to_forecast_only_when_enabled(self):
        prompt, decision = self._classify(enabled=True)
        self.assertIn("Cadastro da conta de água", prompt)
        self.assertEqual(decision.agents, ["forecast"])

    def test_disabled_flag_leaves_the_router_prompt_unchanged(self):
        prompt, _ = self._classify(enabled=False)
        self.assertNotIn("Cadastro da conta de água", prompt)

    def test_organization_accounts_do_not_get_the_hint(self):
        prompt, _ = self._classify(enabled=True, access_kind="organizational")
        self.assertNotIn("Cadastro da conta de água", prompt)


if __name__ == "__main__":
    unittest.main()
