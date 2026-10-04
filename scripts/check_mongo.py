"""Verifica os alvos MongoDB sem depender dos provedores de LLM."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import uuid4

from bson import ObjectId
from pymongo.errors import ConnectionFailure, OperationFailure, PyMongoError

from app.config import ConfigurationError, Settings, get_settings, validate_mongo_config
from app.data import db_mongo
from app.tools.exceptions import (
    DatabaseAccessError,
    DatabaseConnectionError,
    DatabaseQueryError,
)

_TARGETS = (
    ("app", "user_preferences"),
    ("telemetry", "consumption_summary"),
)
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _client_and_database(component: str):
    settings = get_settings()
    validate_mongo_config(component, settings=settings)
    if component == "app":
        return db_mongo.get_app_client(), settings.mongo_db_app
    return db_mongo.get_telemetry_client(), settings.mongo_db_telemetry


def _check_target(component: str, collection_name: str) -> bool:
    client, database_name = _client_and_database(component)
    client.admin.command("ping")
    collection = client[database_name][collection_name]
    document = collection.find_one(
        {},
        projection={"_id": 1},
        max_time_ms=get_settings().db_query_timeout_seconds * 1000,
    )
    state = "documento_encontrado" if document is not None else "sem_documento"
    print(
        f"MongoDB {component}: database={database_name} "
        f"collection={collection_name} ping=ok leitura={state}"
    )
    return document is not None


def _validate_fixture_target(settings: Settings) -> None:
    if settings.app_env != "test":
        raise ConfigurationError("A fixture exige APP_ENV=test.")

    targets = (
        ("app", settings.mongodb_app_uri, settings.mongo_db_app),
        ("telemetry", settings.mongodb_telemetry_uri, settings.mongo_db_telemetry),
    )
    for component, uri, database_name in targets:
        validate_mongo_config(component, settings=settings)
        try:
            parsed = urlsplit(uri or "")
            host = parsed.hostname
            scheme = parsed.scheme
            authority = parsed.netloc.rsplit("@", 1)[-1]
            port = parsed.port
        except ValueError:
            host = None
            scheme = None
            authority = ""
            port = None
        if (
            scheme != "mongodb"
            or host not in _LOCAL_HOSTS
            or "," in authority
            or port is None
            or not 1 <= port <= 65535
        ):
            raise ConfigurationError(
                "A fixture exige uma URI mongodb com porta explícita e um único host local."
            )
        if not database_name.casefold().startswith("delta_test_"):
            raise ConfigurationError(
                "A fixture exige databases com prefixo delta_test_."
            )

    if settings.mongo_db_app == settings.mongo_db_telemetry:
        raise ConfigurationError("Os databases de fixture devem ser distintos.")


def _run_fixture(settings: Settings) -> None:
    _validate_fixture_target(settings)
    app_client, _ = _client_and_database("app")
    telemetry_client, _ = _client_and_database("telemetry")
    app_client.admin.command("ping")
    telemetry_client.admin.command("ping")

    app_collection = app_client[settings.mongo_db_app]["user_preferences"]
    telemetry_collection = telemetry_client[settings.mongo_db_telemetry][
        "consumption_summary"
    ]
    query_timeout_ms = settings.db_query_timeout_seconds * 1000
    user_id = 1_700_000_000 + (uuid4().int % 200_000_000)
    app_id = ObjectId()
    telemetry_id = ObjectId()
    device_id = f"fixture-{uuid4().hex}"
    now = datetime.now(timezone.utc)
    app_document = {
        "_id": app_id,
        "user_id": user_id,
        "daily_liters_target": 321,
        "dark_mode_enabled": False,
    }
    telemetry_document = {
        "_id": telemetry_id,
        "device_id": device_id,
        "user_id": user_id,
        "window_started_at": now - timedelta(minutes=5),
        "window_finished_at": now,
        "consumption_liters": 12.75,
        "anomaly_detected": False,
    }

    try:
        if (
            app_collection.find_one(
                {"user_id": user_id},
                {"_id": 1},
                max_time_ms=query_timeout_ms,
            )
            is not None
        ):
            raise RuntimeError("O identificador sintético já está em uso.")
        if (
            telemetry_collection.find_one(
                {"user_id": user_id},
                {"_id": 1},
                max_time_ms=query_timeout_ms,
            )
            is not None
        ):
            raise RuntimeError("O identificador sintético já está em uso.")

        app_collection.insert_one(app_document)
        telemetry_collection.insert_one(telemetry_document)

        target = db_mongo.get_daily_liters_target(user_id)
        history = db_mongo.get_consumption_history(user_id, days=1)
        app_read = app_collection.find_one(
            {"_id": app_id},
            {"_id": 1},
            max_time_ms=query_timeout_ms,
        )
        telemetry_read = telemetry_collection.find_one(
            {"_id": telemetry_id},
            {"_id": 1},
            max_time_ms=query_timeout_ms,
        )
        if (
            target != 321.0
            or len(history) != 1
            or history[0].consumption_liters != 12.75
            or history[0].device_id != device_id
            or app_read is None
            or telemetry_read is None
        ):
            raise RuntimeError("A leitura sintética não corresponde ao documento criado.")

        print(
            f"MongoDB fixture app: database={settings.mongo_db_app} "
            "collection=user_preferences leitura=convertida"
        )
        print(
            f"MongoDB fixture telemetry: database={settings.mongo_db_telemetry} "
            "collection=consumption_summary leitura=convertida"
        )
    finally:
        cleanup_errors = []
        for collection, document_id in (
            (app_collection, app_id),
            (telemetry_collection, telemetry_id),
        ):
            try:
                collection.delete_one({"_id": document_id})
            except Exception:
                cleanup_errors.append(True)
        if cleanup_errors:
            raise RuntimeError("Não foi possível limpar a fixture sintética.")


def _safe_error_message(error: Exception) -> str:
    if isinstance(error, (ConfigurationError, DatabaseAccessError)):
        return str(error)
    if isinstance(error, ConnectionFailure) or (
        isinstance(error, OperationFailure) and error.code in {13, 18}
    ):
        return str(DatabaseConnectionError("MongoDB"))
    if isinstance(error, PyMongoError):
        return str(
            DatabaseQueryError("MongoDB", code=getattr(error, "code", None))
        )
    return "Falha inesperada ao verificar o MongoDB."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture",
        action="store_true",
        help="insere e remove documentos sintéticos somente em databases locais de teste",
    )
    args = parser.parse_args(argv)
    status = 0

    try:
        settings = get_settings()
        if args.fixture:
            _run_fixture(settings)
        else:
            for component, collection_name in _TARGETS:
                try:
                    _check_target(component, collection_name)
                except Exception as exc:
                    print(
                        f"MongoDB {component}: erro={_safe_error_message(exc)}",
                        file=sys.stderr,
                    )
                    status = 1
    except Exception as exc:
        print(_safe_error_message(exc), file=sys.stderr)
        status = 2 if isinstance(exc, ConfigurationError) else 1
    finally:
        try:
            db_mongo.close_clients()
        except Exception as exc:
            print(_safe_error_message(exc), file=sys.stderr)
            status = 1

    return status


if __name__ == "__main__":
    raise SystemExit(main())
