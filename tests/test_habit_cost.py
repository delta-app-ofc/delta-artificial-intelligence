"""Testa o custo da água de hábitos sem consultar o banco de dados."""

import unittest
from decimal import Decimal
from unittest.mock import patch

from app.tools.exceptions import DatabaseConnectionError, RegionRateNotFound
from app.tools.habits import tools as habit_tools
from app.tools.habits.calculations import estimate_habit_cost


def _tool(access_kind="residential"):
    tools = habit_tools.build_tools(7, access_kind)
    return {t.name: t for t in tools}["estimate_habit_water_cost"]


ARGS = {"habit_name": "lavar roupa", "frequency": 3}


class HabitCostCalculationTest(unittest.TestCase):
    def test_reference_case(self):
        cost = estimate_habit_cost(100, 3, Decimal("10"))
        self.assertEqual(cost.liters_per_week, Decimal("300"))
        self.assertEqual(cost.liters_per_month, Decimal("1299.00"))
        self.assertEqual(cost.cost_per_month, Decimal("12.99"))

    def test_rounds_half_up(self):
        self.assertEqual(estimate_habit_cost(100, 1, Decimal("0.0115")).cost_per_month, Decimal("0.00"))
        self.assertEqual(estimate_habit_cost(1000, 1, Decimal("0.11547")).cost_per_month, Decimal("0.50"))

    def test_rejects_invalid_values(self):
        with self.assertRaises(ValueError):
            estimate_habit_cost(0, 3, 10)
        with self.assertRaises(ValueError):
            estimate_habit_cost(100, 0, 10)
        with self.assertRaises(ValueError):
            estimate_habit_cost(100, 3, -1)


class HabitCostToolTest(unittest.TestCase):
    def _run(self, tool_args=ARGS, access_kind="residential", **pg):
        defaults = {
            "get_user_region_id": 1,
            "get_user_property_classification_id": 2,
            "get_current_region_rate": Decimal("10"),
        }
        defaults.update(pg)
        patches = [
            patch.object(habit_tools.db_postgres, name, side_effect=v if isinstance(v, Exception) else None,
                         return_value=None if isinstance(v, Exception) else v)
            for name, v in defaults.items()
        ]
        for p in patches:
            p.start()
        try:
            return _tool(access_kind).invoke(tool_args)
        finally:
            for p in patches:
                p.stop()

    def test_ok_with_rate(self):
        out = self._run()
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["liters_per_week"], 300.0)
        self.assertEqual(out["liters_per_month"], 1299.0)
        self.assertEqual(out["cost_per_month"], 12.99)
        self.assertEqual(out["liters_source"], "média de referência")

    def test_uses_informed_liters(self):
        out = self._run({**ARGS, "liters_per_session": 50})
        self.assertEqual(out["liters_per_week"], 150.0)
        self.assertEqual(out["liters_source"], "informado pelo usuário")

    def test_rate_unavailable_returns_only_liters(self):
        out = self._run(get_current_region_rate=RegionRateNotFound("sem tarifa"))
        self.assertEqual(out["status"], "rate_unavailable")
        self.assertEqual(out["liters_per_month"], 1299.0)
        self.assertNotIn("cost_per_month", out)

    def test_property_not_identified(self):
        out = self._run(get_user_region_id=None)
        self.assertEqual(out["status"], "property_not_found")
        self.assertNotIn("cost_per_month", out)

    def test_database_failure_is_not_missing_data(self):
        out = self._run(get_user_region_id=DatabaseConnectionError("PostgreSQL"))
        self.assertEqual(out["status"], "error")

    def test_organization_is_not_applicable(self):
        out = self._run(access_kind="organizational")
        self.assertEqual(out["status"], "not_applicable")

    def test_invalid_input(self):
        self.assertEqual(self._run({**ARGS, "frequency": 0})["status"], "error")
        self.assertEqual(self._run({**ARGS, "habit_name": "voar"})["status"], "error")

    def test_user_id_is_not_in_the_schema(self):
        self.assertNotIn("user_id", _tool().args)


if __name__ == "__main__":
    unittest.main()
