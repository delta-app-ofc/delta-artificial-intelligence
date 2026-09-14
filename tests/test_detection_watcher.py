"""Testes de `process_event` — a lógica pura do watcher, sem Mongo real e sem
Change Stream (só a função que decide o que fazer com UM documento)."""

from __future__ import annotations

from datetime import datetime, timedelta

from detection.watcher import _doc_to_consumption_point, process_event


def _doc(when: datetime, liters: float) -> dict:
    return {
        "device_id": "ESP32TEST",
        "user_id": 1,
        "window_started_at": when,
        "window_finished_at": when + timedelta(minutes=5),
        "consumption_liters": liters,
        "lpm_average": liters / 5,
        "anomaly_detected": False,
    }


def test_doc_to_consumption_point_conversion():
    when = datetime(2026, 9, 15, 3, 0, 0)
    point = _doc_to_consumption_point(_doc(when, 1.5))
    assert point.user_id == 1
    assert point.device_id == "ESP32TEST"
    assert point.consumption_liters == 1.5


def test_process_event_flags_continuous_overnight_flow():
    base = datetime(2026, 9, 15, 3, 0, 0)
    recent_docs = [_doc(base + timedelta(minutes=5 * i), 1.5) for i in range(6)]
    recent_history = [_doc_to_consumption_point(d) for d in recent_docs]
    current_doc = _doc(base + timedelta(minutes=5 * 6), 1.5)

    # hour_mean/hour_std = 0.0: sem baseline ainda pra esse usuário/hora — as
    # regras de fluxo contínuo e madrugada não dependem disso.
    result = process_event(
        current_doc, recent_history, 0.0, 0.0, "RESIDENCIAL", z_threshold=3.0
    )
    assert result.anomaly_detected is True
    assert "continuous_flow" in result.reasons
    assert "overnight_consumption" in result.reasons


def test_process_event_does_not_flag_an_isolated_daytime_window():
    when = datetime(2026, 9, 15, 12, 0, 0)
    current_doc = _doc(when, 5.0)

    result = process_event(current_doc, [], 0.0, 0.0, "RESIDENCIAL", z_threshold=3.0)
    assert result.anomaly_detected is False
    assert result.reasons == []
