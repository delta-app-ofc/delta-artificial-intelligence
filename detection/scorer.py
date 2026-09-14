"""Combina regras + modelo numa decisão só, com os motivos explicáveis."""

from __future__ import annotations

from dataclasses import dataclass

from detection import rules
from detection.features import extract_features


@dataclass(frozen=True)
class DetectionResult:
    anomaly_detected: bool
    reasons: list[str]
    model_score: float


def evaluate_window(
    window, recent_history, hour_mean, hour_std, property_classification,
    model, z_threshold: float,
) -> DetectionResult:
    features = extract_features(window, recent_history, hour_mean, hour_std)
    reasons: list[str] = []

    if rules.continuous_flow_rule(features):
        reasons.append("continuous_flow")
    if rules.overnight_rule(features, property_classification):
        reasons.append("overnight_consumption")
    if rules.extreme_deviation_rule(features, z_threshold):
        reasons.append("baseline_deviation")

    vector = [features.to_vector()]
    score = float(model.decision_function(vector)[0])
    if model.predict(vector)[0] == -1:
        reasons.append("atypical_multivariate_pattern")

    return DetectionResult(anomaly_detected=bool(reasons), reasons=reasons, model_score=score)
