"""Testa o cadastro de hábitos em linguagem natural sem banco nem LLM reais."""

import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import psycopg2.errors
from langchain_core.messages import AIMessage

from app.agents._runtime import run_agent
from app.agents.habits import HabitsAgent
from app.data import db_postgres
from app.tools.exceptions import DatabaseConnectionError, HabitConflictError
from app.tools.habits import tools as habit_tools
from app.tools.habits.names import resolve_habit_name


def _tools(access_kind="residential"):
    return {t.name: t for t in habit_tools.build_tools(7, access_kind)}


def _saved(**extra):
    base = {"habit_id": 41, "name": "LAVAR ROUPA", "frequency": 3, "days": [],
            "start_time": None, "end_time": None}
    return {**base, **extra}


class ResolveHabitNameTest(unittest.TestCase):
    def test_variants_map_to_catalog(self):
        for text in ["lavar roupa", "lavar roupas", "Lavar a Roupa", "roupas", "tomar banho",
                     "lavar louca", "lavar louça", "carro", "plantas"]:
            with self.subTest(text=text):
                self.assertIsNotNone(resolve_habit_name(text)[0])

    def test_ambiguous_returns_options(self):
        name, options = resolve_habit_name("lavar")
        self.assertIsNone(name)
        self.assertEqual(len(options), 4)

    def test_unknown_name_has_no_options(self):
        self.assertEqual(resolve_habit_name("regar jardim"), (None, []))


class CreateHabitToolTest(unittest.TestCase):
    def _create(self, args, **db):
        db.setdefault("return_value", _saved())
        with patch.object(habit_tools.db_postgres, "create_habit", **db) as create:
            return _tools()["create_habit"].invoke(args), create

    def test_days_and_times_are_optional_in_the_schema(self):
        schema = _tools()["create_habit"].args_schema.model_json_schema()
        self.assertEqual(schema["required"], ["name"])

    def test_omitted_days_do_not_fail_and_nothing_is_invented(self):
        out, create = self._create({"name": "lavar roupa", "frequency": 3})
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["habit_id"], 41)
        create.assert_called_once_with(7, "LAVAR ROUPA", 3, [], None, None)

    def test_plural_and_alias_variants_are_saved_with_canonical_name(self):
        for text in ["lavar roupas", "roupas", "Lavar a roupa"]:
            with self.subTest(text=text):
                _, create = self._create({"name": text, "frequency": 3})
                self.assertEqual(create.call_args.args[1], "LAVAR ROUPA")

    def test_ambiguous_name_asks_instead_of_saving(self):
        out, create = self._create({"name": "lavar", "frequency": 2})
        self.assertEqual(out["status"], "needs_clarification")
        self.assertEqual(len(out["options"]), 4)
        create.assert_not_called()

    def test_unknown_name_does_not_save(self):
        out, create = self._create({"name": "regar jardim", "frequency": 2})
        self.assertEqual(out["status"], "error")
        create.assert_not_called()

    def test_days_are_normalized_deduplicated_and_give_the_frequency(self):
        out, create = self._create({"name": "lavar carro", "days": ["seg", "Sexta", "segunda"]})
        self.assertEqual(out["status"], "ok")
        create.assert_called_once_with(7, "LAVAR CARRO", 2, ["SEGUNDA", "SEXTA"], None, None)

    def test_missing_frequency_and_days_asks_for_frequency(self):
        out, create = self._create({"name": "lavar carro"})
        self.assertEqual(out["status"], "needs_frequency")
        create.assert_not_called()

    def test_more_days_than_frequency_asks_for_clarification(self):
        out, create = self._create({"name": "lavar carro", "frequency": 1, "days": ["seg", "sex"]})
        self.assertEqual(out["status"], "needs_clarification")
        create.assert_not_called()

    def test_invalid_day_does_not_save(self):
        out, create = self._create({"name": "lavar carro", "frequency": 1, "days": ["feriado"]})
        self.assertEqual(out["status"], "error")
        create.assert_not_called()

    def test_times_are_validated_and_normalized(self):
        out, create = self._create(
            {"name": "lavar carro", "frequency": 1, "days": ["seg"],
             "start_time": "18h", "end_time": "19:30"}
        )
        self.assertEqual(out["status"], "ok")
        self.assertEqual(create.call_args.args[4:], ("18:00", "19:30"))

        for bad in [{"start_time": "18:00"}, {"start_time": "19:00", "end_time": "18:00"},
                    {"start_time": "25:00", "end_time": "26:00"}]:
            with self.subTest(bad=bad):
                out, create = self._create({"name": "lavar carro", "frequency": 1, **bad})
                self.assertEqual(out["status"], "error")
                create.assert_not_called()

    def test_conflict_is_reported_and_not_confirmed(self):
        out, _ = self._create(
            {"name": "lavar carro", "frequency": 1},
            side_effect=HabitConflictError("Você já tem esse hábito cadastrado nesse dia e horário."),
        )
        self.assertEqual(out["status"], "conflict")
        self.assertNotIn("habit_id", out)

    def test_bank_refusal_and_database_outage_are_not_success(self):
        out, _ = self._create({"name": "lavar carro", "frequency": 1}, side_effect=ValueError("recusado"))
        self.assertEqual(out["status"], "error")
        out, _ = self._create(
            {"name": "lavar carro", "frequency": 1}, side_effect=DatabaseConnectionError("PostgreSQL")
        )
        self.assertEqual(out["status"], "error")
        self.assertIn("Nada foi cadastrado", out["message"])

    def test_organization_account_cannot_create(self):
        with patch.object(habit_tools.db_postgres, "create_habit") as create:
            out = _tools("organizational")["create_habit"].invoke({"name": "lavar carro", "frequency": 1})
        self.assertEqual(out["status"], "not_applicable")
        create.assert_not_called()

    def test_user_id_is_not_exposed(self):
        self.assertNotIn("user_id", _tools()["create_habit"].args)


class FakeRaiseException(psycopg2.errors.RaiseException):
    """RaiseException com a mensagem do banco, que o psycopg2 não permite montar à mão."""

    def __init__(self, message):
        super().__init__(message)
        self._message = message

    @property
    def diag(self):
        return MagicMock(message_primary=self._message)


class DatabaseLayerTest(unittest.TestCase):
    def _cursor(self, execute_error=None, row=(41,)):
        cur = MagicMock()
        cur.execute.side_effect = execute_error
        cur.fetchone.return_value = row

        @contextmanager
        def fake_cursor(*args, **kwargs):
            yield cur

        return patch.object(db_postgres, "_cursor", fake_cursor), cur

    def test_returns_the_id_written_by_the_database(self):
        ctx, cur = self._cursor()
        with ctx:
            out = db_postgres.create_habit(7, "LAVAR ROUPA", 3, [], None, None)
        self.assertEqual(out["habit_id"], 41)
        self.assertIn("fn_create_user_habit", cur.execute.call_args.args[0])

    def test_conflict_message_becomes_conflict_error(self):
        ctx, _ = self._cursor(FakeRaiseException("O usuário já possui esse hábito nesse dia e horário."))
        with ctx, self.assertRaises(HabitConflictError):
            db_postgres.create_habit(7, "LAVAR ROUPA", 3, ["SEGUNDA"])

    def test_other_refusals_become_generic_value_error(self):
        ctx, _ = self._cursor(FakeRaiseException("Dia da semana inválido em {X}."))
        with ctx, self.assertRaises(ValueError) as caught:
            db_postgres.create_habit(7, "LAVAR ROUPA", 3, ["X"])
        self.assertNotIsInstance(caught.exception, HabitConflictError)
        self.assertNotIn("{X}", str(caught.exception))

    def test_missing_id_is_not_success(self):
        ctx, _ = self._cursor(row=None)
        with ctx, self.assertRaises(Exception):
            db_postgres.create_habit(7, "LAVAR ROUPA", 3, [])


class ScriptedLLM:
    """LLM falso: devolve as respostas na ordem e registra o que recebeu."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []

    def bind_tools(self, tools):
        self.tool_names = [t.name for t in tools]
        return self

    def invoke(self, messages):
        self.seen.append(messages)
        return self.replies.pop(0)


def _call(name, args, call_id="c1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


class CreateFlowTest(unittest.TestCase):
    def test_create_request_goes_to_create_habit_not_to_listing(self):
        llm = ScriptedLLM([
            _call("create_habit", {"name": "lavar roupas", "frequency": 3}),
            AIMessage(content="Hábito Lavar Roupa cadastrado."),
        ])
        with (
            patch.object(habit_tools.db_postgres, "create_habit", return_value=_saved()) as create,
            patch.object(habit_tools.db_postgres, "get_user_habits") as listing,
        ):
            result = run_agent(llm=llm, system_prompt="p", tools=list(_tools().values()),
                               question="Adicione lavar roupas 3x na semana")
        create.assert_called_once()
        listing.assert_not_called()
        self.assertEqual(result.tool_calls[0].output["status"], "ok")

    def test_incomplete_request_is_completed_in_the_next_turn_with_history(self):
        history = "Conversa recente:\nuser: Cadastra regar plantas\nassistant: Quantas vezes por semana?"
        question = f"2 vezes\n\n{history}"
        llm = ScriptedLLM([
            _call("create_habit", {"name": "regar plantas", "frequency": 2}),
            AIMessage(content="Cadastrado."),
        ])
        with patch.object(habit_tools.db_postgres, "create_habit",
                          return_value=_saved(name="REGAR PLANTAS", frequency=2)) as create:
            run_agent(llm=llm, system_prompt="p", tools=list(_tools().values()), question=question)
        self.assertIn("Cadastra regar plantas", llm.seen[0][1].content)
        create.assert_called_once_with(7, "REGAR PLANTAS", 2, [], None, None)

    def test_read_only_tools_never_write(self):
        llm = ScriptedLLM([
            _call("estimate_habit_water_impact", {"habit_name": "lavar roupa", "frequency": 3}),
            AIMessage(content="São 300 L por semana."),
        ])
        with patch.object(habit_tools.db_postgres, "create_habit") as create:
            run_agent(llm=llm, system_prompt="p", tools=list(_tools().values()), question="Quanto gasto?")
        create.assert_not_called()


class JudgeRevisionGuardTest(unittest.TestCase):
    def _run(self, **kwargs):
        with (
            patch("app.agents.habits.run_agent") as run,
            patch("app.agents.habits.build_habits_chart", return_value=None),
        ):
            run.return_value = MagicMock()
            HabitsAgent(7, llm=object(), access_kind="residential").run("cadastre", **kwargs)
        return [t.name for t in run.call_args.kwargs["tools"]]

    def test_first_pass_can_write(self):
        self.assertIn("create_habit", self._run())

    def test_revision_pass_cannot_write(self):
        self.assertNotIn("create_habit", self._run(revision_feedback="corrija"))
        self.assertNotIn("create_habit", self._run(revision_context={"previous_candidate": "x"}))
        self.assertIn("list_habits", self._run(revision_feedback="corrija"))


if __name__ == "__main__":
    unittest.main()
