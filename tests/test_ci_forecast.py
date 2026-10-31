"""Verificações isoladas da previsão determinística, sem serviços externos."""

import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal

from app.tools.exceptions import ForecastUnavailableError
from app.tools.forecast.calculations import calculate_full_forecast
from app.tools.models import ConsumptionPoint


class ForecastSmokeTest(unittest.TestCase):
    def test_projection_and_bill_from_seven_days(self):
        history = [
            ConsumptionPoint(1, datetime(2026, 4, day), datetime(2026, 4, day) + timedelta(hours=1), 100, False)
            for day in range(1, 8)
        ]
        result = calculate_full_forecast(
            can_estimate=True, history=history, last_bill=None,
            region_rate=Decimal("5.00"), daily_target=90, today=date(2026, 4, 7),
        )
        self.assertTrue(result.has_enough_history)
        self.assertEqual(result.projection.month_projection_liters, 3000)
        self.assertEqual(result.bill.estimated_value, Decimal("15.00"))
        self.assertTrue(result.target_risk.at_risk)

    def test_ineligible_user_cannot_be_estimated(self):
        with self.assertRaises(ForecastUnavailableError):
            calculate_full_forecast(
                can_estimate=False, history=[], last_bill=None,
                region_rate=None, daily_target=None, today=date(2026, 4, 7),
            )


if __name__ == "__main__":
    unittest.main()
