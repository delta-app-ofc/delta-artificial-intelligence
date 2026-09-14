from __future__ import annotations

from dataclasses import dataclass

from detection import rules
from detection.features import extract_features


@dataclass(frozen=True)
class DetectionResult:
    anomaly_detected: bool
    reasons: list[str]


def evaluate_window(
    window, recent_history, hour_mean, hour_std, property_classification, z_threshold: float,
) -> DetectionResult:
    features = extract_features(window, recent_history, hour_mean, hour_std)
    reasons: list[str] = []

    if rules.continuous_flow_rule(features):
        reasons.append("continuous_flow")
    if rules.overnight_rule(features, property_classification):
        reasons.append("overnight_consumption")
    if rules.extreme_deviation_rule(features, z_threshold):
        reasons.append("baseline_deviation")

    return DetectionResult(anomaly_detected=bool(reasons), reasons=reasons)
