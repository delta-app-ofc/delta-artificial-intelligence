from pathlib import Path
from tempfile import NamedTemporaryFile

import pytest

from app.config import (
    ConfigurationError,
    get_postgres_connection_args,
    get_settings,
    load_settings,
    validate_llm_config,
    validate_mongo_config,
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


def test_test_environment_does_not_read_an_explicit_env_file() -> None:
    with NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix="settings-test-",
        suffix=".env.example",
        dir=Path(__file__).parent,
        delete=False,
    ) as env_file:
        env_file.write(
            "DATABASE_URL=postgresql://file-user:file-pass@file-host/file-db\n"
            "GEMINI_API_KEY=file-key-placeholder\n"
        )
        env_path = Path(env_file.name)

    try:
        settings = load_settings(environ={"APP_ENV": "test"}, env_file=env_path)
    finally:
        env_path.unlink(missing_ok=True)

    assert settings.database_url is None
    assert settings.gemini_api_key is None


def test_dotenv_interpolation_does_not_use_process_secrets() -> None:
    with NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix="settings-test-",
        suffix=".env.example",
        dir=Path(__file__).parent,
        delete=False,
    ) as env_file:
        env_file.write("APP_ENV=development\nGEMINI_API_KEY=${EXTERNAL_KEY}\n")
        env_path = Path(env_file.name)

    try:
        settings = load_settings(
            environ={"APP_ENV": "development", "EXTERNAL_KEY": "synthetic-external-key"},
            env_file=env_path,
        )
    finally:
        env_path.unlink(missing_ok=True)

    assert settings.gemini_api_key == "${EXTERNAL_KEY}"


def test_explicit_empty_database_url_does_not_use_development_default() -> None:
    settings = load_settings(environ={"APP_ENV": "development", "DATABASE_URL": ""})

    assert settings.database_url is None
    with pytest.raises(ConfigurationError, match="DATABASE_URL"):
        validate_postgres_config(settings=settings)


def test_mongo_accepts_replica_sets_and_ipv6_without_llm_keys() -> None:
    settings = load_settings(
        environ={
            "APP_ENV": "staging",
            "MONGODB_APP_URI": (
                "mongodb://user:p%40ss@host1:27017,host2:27018/app?replicaSet=rs0"
            ),
            "MONGODB_TELEMETRY_URI": "mongodb://[2001:db8::1]:27017/telemetry",
        }
    )

    validate_mongo_config("app", settings=settings)
    validate_mongo_config("telemetry", settings=settings)

    assert settings.mongodb_app_uri != settings.mongodb_telemetry_uri
    assert settings.gemini_api_key is None
    assert settings.groq_api_key is None


def test_mongo_srv_uri_is_valid_without_a_port() -> None:
    settings = load_settings(
        environ={
            "APP_ENV": "production",
            "MONGODB_APP_URI": (
                "mongodb+srv://user:p%40ss@cluster.example.invalid/db?retryWrites=true"
            ),
        }
    )

    validate_mongo_config("app", settings=settings)


@pytest.mark.parametrize(
    "uri",
    [
        "mongodb://host:70000/db",
        "mongodb://host:not-a-port/db",
        "mongodb+srv://host1,host2/db",
        "mongodb+srv://host:27017/db",
        "mongodb://[not-ipv6]:27017/db",
    ],
)
def test_invalid_mongo_authorities_are_rejected(uri: str) -> None:
    settings = load_settings(environ={"APP_ENV": "staging", "MONGODB_APP_URI": uri})

    with pytest.raises(ConfigurationError, match="MONGODB_APP_URI"):
        validate_mongo_config("app", settings=settings)


def test_empty_mongo_uri_and_database_name_are_not_replaced_by_defaults() -> None:
    settings = load_settings(
        environ={
            "APP_ENV": "development",
            "MONGODB_APP_URI": "",
            "MONGO_DB_APP": "",
        }
    )

    with pytest.raises(ConfigurationError) as captured:
        validate_mongo_config("app", settings=settings)

    assert "MONGODB_APP_URI" in str(captured.value)
    assert "MONGO_DB_APP" in str(captured.value)


def test_selected_llm_path_does_not_require_unselected_provider_keys() -> None:
    settings = load_settings(
        environ={
            "APP_ENV": "test",
            "GEMINI_API_KEY": "synthetic-gemini-key",
            "MONGODB_APP_URI": "mongodb://localhost:27018",
        }
    )

    validate_llm_config("gemini", settings=settings)
    validate_mongo_config("app", settings=settings)


@pytest.mark.parametrize(
    ("name", "value", "provider"),
    [
        ("LLM_FALLBACK_ENABLED", "sometimes", "specialist"),
        ("LLM_TIMEOUT_SECONDS", "0", "gemini"),
        ("LLM_MAX_RETRIES", "-1", "gemini"),
        ("LLM_MAX_OUTPUT_TOKENS", "0", "gemini"),
    ],
)
def test_invalid_llm_settings_are_rejected(name: str, value: str, provider: str) -> None:
    settings = load_settings(
        environ={
            "APP_ENV": "test",
            "GEMINI_API_KEY": "synthetic-gemini-key",
            "GROQ_API_KEY": "synthetic-groq-key",
            name: value,
        }
    )

    with pytest.raises(ConfigurationError, match=name):
        validate_llm_config(provider, settings=settings)


def test_settings_repr_hides_keys_and_connection_uris() -> None:
    secret = "synthetic-secret-that-must-not-appear"
    settings = load_settings(
        environ={
            "APP_ENV": "test",
            "GEMINI_API_KEY": secret,
            "GROQ_API_KEY": secret,
            "DATABASE_URL": f"postgresql://user:{secret}@db.invalid/app",
            "MONGODB_APP_URI": f"mongodb://user:{secret}@mongo.invalid/app",
        }
    )

    assert secret not in repr(settings)
    assert "postgresql://" not in repr(settings)
    assert "mongodb://" not in repr(settings)
