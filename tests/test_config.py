from pathlib import Path
from tempfile import NamedTemporaryFile

import pytest

from app.config import (
    ConfigurationError,
    get_postgres_connection_args,
    get_settings,
    load_settings,
    validate_postgres_config,
)


def test_development_defaults_match_local_services() -> None:
    settings = load_settings(environ={"APP_ENV": "development"})

    assert settings.app_env == "development"
    assert settings.database_url == "postgresql://postgres:postgres@localhost:5432/postgres"
    assert settings.mongodb_app_uri == "mongodb://localhost:27018"
    assert settings.mongodb_telemetry_uri == "mongodb://localhost:27018"
    assert settings.mongo_db_app == "db_delta_app"
    assert settings.mongo_db_telemetry == "db_delta_telemetry"


def test_test_environment_has_no_local_database_fallbacks() -> None:
    settings = load_settings(environ={"APP_ENV": "test"})

    assert settings.app_env == "test"
    assert settings.database_url is None
    assert settings.mongodb_app_uri is None
    assert settings.mongodb_telemetry_uri is None
    assert settings.gemini_api_key is None
    assert settings.groq_api_key is None


def test_process_environment_precedes_env_file() -> None:
    with NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix="settings-test-",
        suffix=".env.example",
        dir=Path(__file__).parent,
        delete=False,
    ) as env_file:
        env_file.write(
            "APP_ENV=development\nDATABASE_URL=postgresql://file-user:file-pass@file-host/file-db\n"
        )
        env_path = Path(env_file.name)

    try:
        settings = load_settings(
            environ={
                "APP_ENV": "development",
                "DATABASE_URL": "postgresql://process-user:process-pass@process-host/process-db",
            },
            env_file=env_path,
        )
    finally:
        env_path.unlink(missing_ok=True)

    assert settings.database_url == "postgresql://process-user:process-pass@process-host/process-db"


def test_postgres_split_settings_take_precedence_over_database_url() -> None:
    settings = load_settings(
        environ={
            "APP_ENV": "staging",
            "DATABASE_URL": "postgresql://url-user:url-pass@url-host/url-db",
            "HOST_DB": "split-host",
            "PORT_DB": "5432",
            "USER_DB": "split-user",
            "PASSWORD_DB": "split-password",
            "NAME_DB": "split-db",
        }
    )

    assert settings.database_url == "postgresql://url-user:url-pass@url-host/url-db"
    assert settings.postgres_split_requested
    args = get_postgres_connection_args(settings=settings)
    assert args["host"] == "split-host"
    assert args["port"] == 5432
    assert "dsn" not in args


def test_explicit_empty_split_setting_does_not_fall_back_to_database_url() -> None:
    secret = "synthetic-password-that-must-not-appear"
    settings = load_settings(
        environ={
            "APP_ENV": "staging",
            "DATABASE_URL": f"postgresql://url-user:{secret}@url-host/url-db",
            "HOST_DB": "",
        }
    )

    assert settings.postgres_split_requested
    with pytest.raises(ConfigurationError) as captured:
        validate_postgres_config(settings=settings)

    assert "PORT_DB" in str(captured.value)
    assert secret not in str(captured.value)


def test_database_url_is_preserved_with_tls_and_encoded_password() -> None:
    dsn = (
        "postgresql://user:p%40ss%3Aword@db.invalid:5432/app"
        "?sslmode=verify-full&sslrootcert=%2Fcerts%2Froot.pem"
    )
    settings = load_settings(environ={"APP_ENV": "staging", "DATABASE_URL": dsn})

    validate_postgres_config(settings=settings)

    assert get_postgres_connection_args(settings=settings)["dsn"] == dsn


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://user:secret@db.invalid:70000/app",
        "postgresql://user:secret@db.invalid:not-a-port/app",
        "mysql://user:secret@db.invalid/app",
    ],
)
def test_invalid_database_url_is_rejected_without_echoing_credentials(dsn: str) -> None:
    settings = load_settings(environ={"APP_ENV": "staging", "DATABASE_URL": dsn})

    with pytest.raises(ConfigurationError) as captured:
        validate_postgres_config(settings=settings)

    assert "DATABASE_URL" in str(captured.value)
    assert "secret" not in str(captured.value)


def test_invalid_postgres_timeout_is_rejected() -> None:
    settings = load_settings(
        environ={
            "APP_ENV": "staging",
            "DATABASE_URL": "postgresql://user:password@db.invalid/app",
            "DB_CONNECT_TIMEOUT_SECONDS": "0",
        }
    )

    with pytest.raises(ConfigurationError, match="DB_CONNECT_TIMEOUT_SECONDS"):
        validate_postgres_config(settings=settings)


def test_settings_cache_can_be_refreshed(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("GEMINI_API_KEY", "first-synthetic-key")
    first = get_settings(refresh=True)

    monkeypatch.setenv("GEMINI_API_KEY", "second-synthetic-key")
    second = get_settings(refresh=True)

    assert first.gemini_api_key == "first-synthetic-key"
    assert second.gemini_api_key == "second-synthetic-key"
    monkeypatch.delenv("GEMINI_API_KEY")
    get_settings(refresh=True)
