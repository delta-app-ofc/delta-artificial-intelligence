from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache

from pymongo import ASCENDING, DESCENDING, MongoClient

from app.config import MONGO_DB_APP, MONGO_DB_TELEMETRY, MONGODB_URI
from app.tools.models import Alert, ConsumptionPoint


@lru_cache(maxsize=1)
def get_client() -> MongoClient:
    return MongoClient(MONGODB_URI, tz_aware=True)


def _telemetry():
    return get_client()[MONGO_DB_TELEMETRY]


def _app():
    return get_client()[MONGO_DB_APP]


def _since(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def _to_point(doc: dict) -> ConsumptionPoint:
    return ConsumptionPoint(
        user_id=int(doc["user_id"]),
        window_started_at=doc["window_started_at"],
        window_finished_at=doc["window_finished_at"],
        consumption_liters=float(doc.get("consumption_liters", 0.0)),
        anomaly_detected=bool(doc.get("anomaly_detected", False)),
        lpm_average=(
            float(doc["lpm_average"]) if doc.get("lpm_average") is not None else None
        ),
        device_id=doc.get("device_id"),
    )


def _to_alert(doc: dict) -> Alert:
    return Alert(
        user_id=int(doc["user_id"]),
        device_id=doc.get("device_id", ""),
        alert_type=doc.get("alert_type", ""),
        triggered_at=doc["triggered_at"],
        resolved_at=doc.get("resolved_at"),
        severity=doc.get("severity"),
    )


# Tools do Agente de Previsão (app/tools/forecast/tools.py)
def get_consumption_history(user_id: int, days: int) -> list[ConsumptionPoint]:
    cursor = (
        _telemetry()
        .consumption_summary.find(
            {"user_id": user_id, "window_started_at": {"$gte": _since(days)}}
        )
        .sort("window_started_at", ASCENDING)
    )
    return [_to_point(doc) for doc in cursor]


def get_daily_liters_target(user_id: int) -> float | None:
    doc = _app().user_preferences.find_one({"user_id": user_id})
    if not doc or doc.get("daily_liters_target") is None:
        return None
    return float(doc["daily_liters_target"])


# Tools do Agente de Vazamento (app/tools/leak/tools.py)
def get_anomalous_consumption_windows(user_id: int, days: int) -> list[ConsumptionPoint]:
    cursor = (
        _telemetry()
        .consumption_summary.find(
            {
                "user_id": user_id,
                "anomaly_detected": True,
                "window_started_at": {"$gte": _since(days)},
            }
        )
        .sort("window_started_at", ASCENDING)
    )
    return [_to_point(doc) for doc in cursor]


def get_alerts_history(
    user_id: int, days: int, only_active: bool = False
) -> list[Alert]:
    query: dict = {
        "user_id": user_id,
        "triggered_at": {"$gte": _since(days)},
    }
    if only_active:
        query["resolved_at"] = None

    cursor = _app().alerts_history.find(query).sort("triggered_at", DESCENDING)
    return [_to_alert(doc) for doc in cursor]
