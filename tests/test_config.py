from pathlib import Path
from tempfile import NamedTemporaryFile

from app.config import get_settings, load_settings


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
        mode="w", encoding="utf-8", prefix="settings-test-", suffix=".env.example", dir=Path(__file__).parent, delete=False
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
