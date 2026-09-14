"""Testes do scorer (regras + Isolation Forest) com um modelo treinado numa
fixture pequena e determinística — sem Mongo."""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta

from app.tools.models import ConsumptionPoint
from detection.features import extract_features, hour_baseline_from_history
from detection.model import train_model
from detection.rules import calibrate_z_threshold
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


def _train_normal_model(history):
    features = [
        extract_features(p, history[max(0, i - 6):i], *hour_baseline_from_history(p.window_started_at.hour, history))
        for i, p in enumerate(history)
    ]
    z_threshold = calibrate_z_threshold([f.baseline_deviation for f in features], percentile=99)
    model = train_model([f.to_vector() for f in features], contamination=0.02)
    return model, z_threshold


def test_obvious_leak_is_flagged_with_the_right_reasons():
    history = _build_normal_history()
    model, z_threshold = _train_normal_model(history)

    leak_windows = _build_leak_windows(TODAY)
    current, recent = leak_windows[-1], leak_windows[:-1]
    hour_mean, hour_std = hour_baseline_from_history(current.window_started_at.hour, history)

    result = evaluate_window(current, recent, hour_mean, hour_std, "RESIDENCIAL", model, z_threshold)
    assert result.anomaly_detected is True
    assert "continuous_flow" in result.reasons
    assert "overnight_consumption" in result.reasons


def test_normal_day_is_not_flagged():
    history = _build_normal_history()
    model, z_threshold = _train_normal_model(history)

    normal_window = history[-1]
    recent = history[-7:-1]
    hour_mean, hour_std = hour_baseline_from_history(normal_window.window_started_at.hour, history)

    result = evaluate_window(normal_window, recent, hour_mean, hour_std, "RESIDENCIAL", model, z_threshold)
    assert result.anomaly_detected is False
    assert result.reasons == []


def test_overnight_rule_is_skipped_for_comercial_property():
    history = _build_normal_history()
    model, z_threshold = _train_normal_model(history)

    leak_windows = _build_leak_windows(TODAY)
    current, recent = leak_windows[-1], leak_windows[:-1]
    hour_mean, hour_std = hour_baseline_from_history(current.window_started_at.hour, history)

    result = evaluate_window(current, recent, hour_mean, hour_std, "COMERCIAL", model, z_threshold)
    assert "overnight_consumption" not in result.reasons
    # o fluxo contínuo continua valendo independente da classificação
    assert "continuous_flow" in result.reasons
