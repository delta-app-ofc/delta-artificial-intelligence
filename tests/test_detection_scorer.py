from __future__ import annotations

import random
from datetime import date, datetime, timedelta

from app.tools.models import ConsumptionPoint
from detection.features import hour_baseline_from_history
from detection.scorer import evaluate_window

TODAY = date(2026, 9, 15)


def _point_at(when: datetime, liters: float) -> ConsumptionPoint:
    return ConsumptionPoint(
        user_id=1, window_started_at=when, window_finished_at=when + timedelta(minutes=5),
        consumption_liters=liters, anomaly_detected=False, lpm_average=liters / 5,
    )


def _build_normal_history(days: int = 20) -> list[ConsumptionPoint]:
    """Dias normais: rajadas curtas de manhã/tarde/noite, nada de madrugada."""
    random.seed(42)
    points = []
    for i in range(days):
        day = TODAY - timedelta(days=days - i)
        for hour in (7, 12, 19):
            when = datetime(day.year, day.month, day.day, hour, 0, 0)
            points.append(_point_at(when, random.uniform(3.0, 8.0)))
    return sorted(points, key=lambda p: p.window_started_at)


def _build_leak_windows(day: date, start_hour: int = 3, count: int = 8) -> list[ConsumptionPoint]:
    """count janelas de 5 min seguidas, todas com fluxo baixo e nunca-zero,
    de madrugada — a assinatura de um vazamento contínuo."""
    base = datetime(day.year, day.month, day.day, start_hour, 0, 0)
    return [
        _point_at(base + timedelta(minutes=5 * i), 1.5)
        for i in range(count)
    ]


def test_obvious_leak_is_flagged_with_the_right_reasons():
    history = _build_normal_history()

    leak_windows = _build_leak_windows(TODAY)
    current, recent = leak_windows[-1], leak_windows[:-1]
    hour_mean, hour_std = hour_baseline_from_history(current.window_started_at.hour, history)

    result = evaluate_window(current, recent, hour_mean, hour_std, "RESIDENCIAL", z_threshold=3.0)
    assert result.anomaly_detected is True
    assert "continuous_flow" in result.reasons
    assert "overnight_consumption" in result.reasons


def test_normal_day_is_not_flagged():
    history = _build_normal_history()

    normal_window = history[-1]
    recent = history[-7:-1]
    hour_mean, hour_std = hour_baseline_from_history(normal_window.window_started_at.hour, history)

    result = evaluate_window(normal_window, recent, hour_mean, hour_std, "RESIDENCIAL", z_threshold=3.0)
    assert result.anomaly_detected is False
    assert result.reasons == []


def test_overnight_rule_is_skipped_for_comercial_property():
    history = _build_normal_history()

    leak_windows = _build_leak_windows(TODAY)
    current, recent = leak_windows[-1], leak_windows[:-1]
    hour_mean, hour_std = hour_baseline_from_history(current.window_started_at.hour, history)

    result = evaluate_window(current, recent, hour_mean, hour_std, "COMERCIAL", z_threshold=3.0)
    assert "overnight_consumption" not in result.reasons
    # o fluxo contínuo continua valendo independente da classificação
    assert "continuous_flow" in result.reasons
