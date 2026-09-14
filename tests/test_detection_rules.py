"""Testes puros das regras de detecção (sem Mongo, sem modelo treinado)."""

from __future__ import annotations

import random

from detection.features import WindowFeatures
from detection.rules import (
    calibrate_z_threshold,
    continuous_flow_rule,
    extreme_deviation_rule,
    overnight_rule,
)


def _features(**overrides) -> WindowFeatures:
    defaults = dict(
        consumption_liters=1.0, is_overnight=0,
        consecutive_flow_windows=0, baseline_deviation=0.0,
    )
    defaults.update(overrides)
    return WindowFeatures(**defaults)


def test_continuous_flow_rule_fires_at_the_threshold():
    assert continuous_flow_rule(_features(consecutive_flow_windows=6)) is True
    assert continuous_flow_rule(_features(consecutive_flow_windows=5)) is False


def test_overnight_rule_fires_for_residential_or_unknown():
    f = _features(is_overnight=1, consumption_liters=2.0)
    assert overnight_rule(f, "RESIDENCIAL") is True
    assert overnight_rule(f, None) is True


def test_overnight_rule_never_fires_for_comercial():
    f = _features(is_overnight=1, consumption_liters=50.0)
    assert overnight_rule(f, "COMERCIAL") is False


def test_overnight_rule_does_not_fire_during_the_day():
    f = _features(is_overnight=0, consumption_liters=50.0)
    assert overnight_rule(f, "RESIDENCIAL") is False


def test_extreme_deviation_rule():
    f = _features(baseline_deviation=5.0)
    assert extreme_deviation_rule(f, z_threshold=3.0) is True
    assert extreme_deviation_rule(f, z_threshold=6.0) is False


def test_calibrate_z_threshold_returns_a_sane_percentile():
    random.seed(0)
    deviations = [random.gauss(0, 1) for _ in range(2000)]
    z = calibrate_z_threshold(deviations, percentile=99)
    # ~99º percentil de |N(0,1)| fica perto de 2.58 — sanidade, não exatidão.
    assert 2.0 < z < 3.5


def test_calibrate_z_threshold_empty_fallback():
    assert calibrate_z_threshold([]) == 3.0
