from datetime import date, datetime, timedelta
from decimal import Decimal

from app.tools.forecast.calculations import (
    assess_target_risk,
    calculate_trend,
    estimate_next_bill,
)
from app.tools.models import ConsumptionPoint, LastWaterBill


def _point(day, liters):
    start = datetime.combine(day, datetime.min.time())
    return ConsumptionPoint(
        user_id=1,
        window_started_at=start,
        window_finished_at=start + timedelta(hours=1),
        consumption_liters=liters,
        anomaly_detected=False,
    )


def test_insufficient_history_uses_last_bill_and_returns_none_without_one():
    today = date(2026, 4, 10)
    history = [_point(date(2026, 4, 9), 100)]
    bill = LastWaterBill(
        user_id=1,
        month=date(2026, 3, 1),
        total_value=Decimal("20.305"),
        m3_value=Decimal("4.25"),
    )

    estimate = estimate_next_bill(history, bill, Decimal("5.00"), today)

    assert estimate.base == "last_bill"
    assert estimate.estimated_value == Decimal("20.31")
    assert estimate.estimated_m3 == Decimal("4.25")
    assert estimate.rate_m3 is None
    assert estimate_next_bill(history, None, None, today) is None


def test_trend_handles_short_history_zero_baseline_and_stable_change():
    today = date(2026, 4, 10)
    short = [_point(date(2026, 4, day), 10) for day in range(1, 6)]
    assert calculate_trend(short, today).direction == "undefined"

    zero_then_positive = [
        _point(date(2026, 4, day), value)
        for day, value in enumerate([0, 0, 0, 10, 10, 10], start=1)
    ]
    trend = calculate_trend(zero_then_positive, today)
    assert trend.direction == "up"
    assert trend.variation_pct is None

    stable = [
        _point(date(2026, 4, day), value)
        for day, value in enumerate([100, 100, 100, 104, 104, 104], start=1)
    ]
    assert calculate_trend(stable, today).direction == "stable"


def test_zero_daily_target_has_no_percentage_denominator():
    risk = assess_target_risk(
        month_projection_liters=5.0,
        daily_target=0,
        days_in_month=30,
    )

    assert risk.assessable is True
    assert risk.at_risk is True
    assert risk.monthly_target_liters == 0
    assert risk.difference_pct is None
