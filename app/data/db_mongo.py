from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Callable, TypeVar

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure, PyMongoError

from app.config import ConfigurationError, get_settings, validate_mongo_config
from app.tools.exceptions import (
    DatabaseAccessError,
    DatabaseConnectionError,
    DatabaseQueryError,
)
from app.tools.models import Alert, ConsumptionPoint

_T = TypeVar("_T")


def _create_client(component: str) -> MongoClient:
    """Valida e cria um cliente lazy para um dos alvos Mongo configurados."""
    settings = get_settings()
    validate_mongo_config(component, settings=settings)

    if component == "app":
        uri = settings.mongodb_app_uri
    else:
        uri = settings.mongodb_telemetry_uri

    connect_timeout_ms = settings.db_connect_timeout_seconds * 1000
    query_timeout_ms = settings.db_query_timeout_seconds * 1000
    try:
        return MongoClient(
            uri,
            tz_aware=True,
            serverSelectionTimeoutMS=connect_timeout_ms,
            connectTimeoutMS=connect_timeout_ms,
            socketTimeoutMS=query_timeout_ms,
        )
    except PyMongoError as exc:
        raise DatabaseConnectionError("MongoDB") from exc


@lru_cache(maxsize=1)
def get_app_client() -> MongoClient:
    return _create_client("app")


@lru_cache(maxsize=1)
def get_telemetry_client() -> MongoClient:
    return _create_client("telemetry")


def close_clients() -> None:
    """Fecha os clientes Mongo inicializados e limpa seus caches."""
    close_error: Exception | None = None
    for client_getter in (get_app_client, get_telemetry_client):
        try:
            if client_getter.cache_info().currsize:
                client_getter().close()
        except Exception as exc:  # continua fechando o outro cliente
            if close_error is None:
                close_error = exc
        finally:
            client_getter.cache_clear()

    if close_error is not None:
        raise DatabaseConnectionError("MongoDB") from close_error


def _telemetry():
    return get_telemetry_client()[get_settings().mongo_db_telemetry]


def _app():
    return get_app_client()[get_settings().mongo_db_app]


def _since(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def _query_timeout_ms(component: str) -> int:
    settings = get_settings()
    validate_mongo_config(component, settings=settings)
    return settings.db_query_timeout_seconds * 1000


def _run_query(action: Callable[[], _T]) -> _T:
    """Converte falhas do driver e documentos inválidos em erros seguros."""
    try:
        return action()
    except DatabaseAccessError:
        raise
    except ConfigurationError:
        raise
    except ConnectionFailure as exc:
        raise DatabaseConnectionError("MongoDB") from exc
    except OperationFailure as exc:
        if exc.code in {13, 18}:
            raise DatabaseConnectionError("MongoDB") from exc
        raise DatabaseQueryError("MongoDB", code=exc.code) from exc
    except PyMongoError as exc:
        raise DatabaseQueryError("MongoDB", code=getattr(exc, "code", None)) from exc
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise DatabaseQueryError("MongoDB") from exc


def _aware_datetime(document: dict, field: str) -> datetime:
    value = document[field]
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("documento contém uma data inválida")
    return value


def _to_point(doc: dict) -> ConsumptionPoint:
    device_id = doc["device_id"]
    if not isinstance(device_id, str):
        raise ValueError("documento contém um identificador inválido")
    return ConsumptionPoint(
        user_id=int(doc["user_id"]),
        window_started_at=_aware_datetime(doc, "window_started_at"),
        window_finished_at=_aware_datetime(doc, "window_finished_at"),
        consumption_liters=float(doc["consumption_liters"]),
        anomaly_detected=bool(doc.get("anomaly_detected", False)),
        lpm_average=(
            float(doc["lpm_average"]) if doc.get("lpm_average") is not None else None
        ),
        device_id=device_id,
    )


def _to_alert(doc: dict) -> Alert:
    device_id = doc["device_id"]
    alert_type = doc["alert_type"]
    resolved_at = doc.get("resolved_at")
    if not isinstance(device_id, str) or not isinstance(alert_type, str):
        raise ValueError("documento contém campos de alerta inválidos")
    if resolved_at is not None and (
        not isinstance(resolved_at, datetime) or resolved_at.utcoffset() is None
    ):
        raise ValueError("documento contém uma data inválida")
    return Alert(
        user_id=int(doc["user_id"]),
        device_id=device_id,
        alert_type=alert_type,
        triggered_at=_aware_datetime(doc, "triggered_at"),
        resolved_at=resolved_at,
        severity=doc.get("severity"),
    )


def _read_many(
    component: str,
    collection_name: str,
    query: dict,
    sort_field: str,
    sort_direction: int,
    converter: Callable[[dict], _T],
) -> list[_T]:
    """Lê e converte documentos mantendo limite de tempo no servidor."""
    def read() -> list[_T]:
        database = _telemetry() if component == "telemetry" else _app()
        collection = database[collection_name]
        cursor = collection.find(query, max_time_ms=_query_timeout_ms(component))
        try:
            return [
                converter(document)
                for document in cursor.sort(sort_field, sort_direction)
            ]
        finally:
            cursor.close()

    return _run_query(read)


def _read_one(component: str, collection_name: str, query: dict) -> dict | None:
    """Lê um documento com limite de execução no servidor."""
    def read() -> dict | None:
        database = _telemetry() if component == "telemetry" else _app()
        return database[collection_name].find_one(
            query,
            max_time_ms=_query_timeout_ms(component),
        )

    return _run_query(read)


# Tools do Agente de Previsão (app/tools/forecast/tools.py)
def get_consumption_history(user_id: int, days: int) -> list[ConsumptionPoint]:
    return _read_many(
        "telemetry",
        "consumption_summary",
        {"user_id": user_id, "window_started_at": {"$gte": _since(days)}},
        "window_started_at",
        ASCENDING,
        _to_point,
    )


def get_daily_liters_target(user_id: int) -> float | None:
    doc = _read_one("app", "user_preferences", {"user_id": user_id})
    if not doc or doc.get("daily_liters_target") is None:
        return None
    return _run_query(lambda: float(doc["daily_liters_target"]))


def get_anomalous_consumption_windows(user_id: int, days: int) -> list[ConsumptionPoint]:
    return _read_many(
        "telemetry",
        "consumption_summary",
        {
            "user_id": user_id,
            "anomaly_detected": True,
            "window_started_at": {"$gte": _since(days)},
        },
        "window_started_at",
        ASCENDING,
        _to_point,
    )


def get_alerts_history(
    user_id: int, days: int, only_active: bool = False
) -> list[Alert]:
    query: dict = {
        "user_id": user_id,
        "triggered_at": {"$gte": _since(days)},
    }
    if only_active:
        query["resolved_at"] = None

    return _read_many(
        "app",
        "alerts_history",
        query,
        "triggered_at",
        DESCENDING,
        _to_alert,
    )
