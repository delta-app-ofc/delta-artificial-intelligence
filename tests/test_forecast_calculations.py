"""Testes do cálculo determinístico da previsão (puro — não depende de banco)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.tools.forecast.calculations import (
    ForecastUnavailableError,
    assess_target_risk,
    calculate_full_forecast,
    calculate_trend,
    estimate_next_bill,
    has_enough_history,
)
from app.tools.models import ConsumptionPoint, LastWaterBill

TODAY = date(2026, 9, 15)  # mês de 30 dias, 15 dias restantes


def _series(today: date, days: int, liters_per_day, hours=(7, 12, 19)) -> list[ConsumptionPoint]:
    points: list[ConsumptionPoint] = []
    for i in range(days):
        day = today - timedelta(days=days - i)
        total = liters_per_day(i)
        per_window = total / len(hours)
        for h in hours:
            start = datetime(day.year, day.month, day.day, h, 0, 0)
            points.append(
                ConsumptionPoint(
                    user_id=1,
                    window_started_at=start,
                    window_finished_at=start + timedelta(minutes=5),
                    consumption_liters=per_window,
                    anomaly_detected=False,
                    lpm_average=per_window / 5,
                )
            )
    return points


def test_first_use_falls_back_to_last_bill():
    last_bill = LastWaterBill(
        user_id=13, month=date(2025, 6, 1),
        total_value=Decimal("142.50"), m3_value=Decimal("19.00"),
    )

    bill = estimate_next_bill([], last_bill, Decimal("6.90"), TODAY)
    assert bill is not None
    assert bill.base == "last_bill"
    assert bill.estimated_value == Decimal("142.50")

    forecast = calculate_full_forecast(
        can_estimate=True, history=[], last_bill=last_bill,
        region_rate=Decimal("6.90"), daily_target=None, today=TODAY,
    )
    assert forecast.has_enough_history is False
    assert forecast.bill.base == "last_bill"
    assert forecast.trend.direction == "undefined"


def test_downward_trend():
    history = _series(TODAY, 40, lambda i: 300 - i * 4)  # 300 -> 144
    assert has_enough_history(history) is True

    trend = calculate_trend(history, TODAY)
    assert trend.direction == "down"
    assert trend.variation_pct is not None and trend.variation_pct < 0
    assert trend.recent_average_liters_per_day < trend.previous_average_liters_per_day


def test_upward_trend_near_target():
    history = _series(TODAY, 40, lambda i: 120 + i * 5)  # 120 -> 315

    trend = calculate_trend(history, TODAY)
    assert trend.direction == "up"

    forecast = calculate_full_forecast(
        can_estimate=True, history=history, last_bill=None,
        region_rate=Decimal("6.90"),
        daily_target=180.0,  # baixo o bastante para a projeção furar a meta
        today=TODAY,
    )
    assert forecast.target_risk.assessable is True
    assert forecast.target_risk.at_risk is True
    assert forecast.bill is not None
    assert forecast.bill.base == "history_projection"


def test_target_risk_without_target_is_not_assessed():
    risk = assess_target_risk(9000.0, None, 30)
    assert risk.assessable is False
    assert risk.at_risk is False


def test_can_estimate_false_raises_and_calculates_nothing():
    history = _series(TODAY, 30, lambda i: 200)
    with pytest.raises(ForecastUnavailableError):
        calculate_full_forecast(
            can_estimate=False, history=history, last_bill=None,
            region_rate=Decimal("6.90"), daily_target=200.0, today=TODAY,
        )
