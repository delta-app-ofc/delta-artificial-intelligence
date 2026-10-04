"""Configuração central da aplicação Delta.

O carregamento não valida integrações automaticamente. Cada componente valida
somente as variáveis de que precisa antes de abrir uma conexão ou criar um LLM.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Literal, Mapping
from urllib.parse import urlsplit

from dotenv import dotenv_values

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"

_ENVIRONMENTS = {"development", "test", "staging", "production"}
_POSTGRES_SPLIT_NAMES = ("HOST_DB", "PORT_DB", "USER_DB", "PASSWORD_DB", "NAME_DB")
_ALL_SETTING_NAMES = frozenset(
    {
        "APP_ENV",
        "GEMINI_API_KEY",
        "GROQ_API_KEY",
        "DATABASE_URL",
        *_POSTGRES_SPLIT_NAMES,
        "MONGODB_APP_URI",
        "MONGODB_TELEMETRY_URI",
        "MONGO_DB_APP",
        "MONGO_DB_TELEMETRY",
        "GEMINI_MODEL",
        "GROQ_SPECIALIST_MODEL",
        "GROQ_FAST_MODEL",
        "LLM_FALLBACK_ENABLED",
        "LLM_TIMEOUT_SECONDS",
        "LLM_MAX_RETRIES",
        "LLM_MAX_OUTPUT_TOKENS",
        "DB_CONNECT_TIMEOUT_SECONDS",
        "DB_QUERY_TIMEOUT_SECONDS",
    }
)


class ConfigurationError(ValueError):
    """Erro seguro de configuração, sem incluir valores das variáveis."""


@dataclass(frozen=True)
class Settings:
    """Snapshot imutável das variáveis de ambiente usadas pela aplicação."""

    app_env: str
    gemini_api_key: str | None = field(repr=False)
    groq_api_key: str | None = field(repr=False)
    database_url: str | None = field(repr=False)
    host_db: str | None = field(repr=False)
    port_db: str | None = field(repr=False)
    user_db: str | None = field(repr=False)
    password_db: str | None = field(repr=False)
    name_db: str | None = field(repr=False)
    mongodb_app_uri: str | None = field(repr=False)
    mongodb_telemetry_uri: str | None = field(repr=False)
    mongo_db_app: str
    mongo_db_telemetry: str
    gemini_model: str
    groq_specialist_model: str
    groq_fast_model: str
    llm_fallback_enabled: bool
    llm_timeout_seconds: float
    llm_max_retries: int
    llm_max_output_tokens: int
    db_connect_timeout_seconds: int
    db_query_timeout_seconds: int
    _provided_names: frozenset[str] = field(default_factory=frozenset, repr=False)
    _parse_errors: tuple[tuple[str, str], ...] = field(default_factory=tuple, repr=False)
    _app_env_error: bool = field(default=False, repr=False)

    @property
    def postgres_split_requested(self) -> bool:
        """True quando pelo menos um nome do formato separado foi informado."""
        return any(name in self._provided_names for name in _POSTGRES_SPLIT_NAMES)


class _DefaultEnvFile:
    pass


_DEFAULT_ENV_FILE = _DefaultEnvFile()


def _has_text(value: str | None) -> bool:
    return value is not None and bool(value.strip())


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text.strip() else None


def _string_setting(values: Mapping[str, object], name: str, default: str) -> str:
    if name not in values:
        return default
    value = values[name]
    return "" if value is None else str(value).strip()


def _parse_int(
    values: Mapping[str, object], name: str, default: int, errors: dict[str, str]
) -> int:
    if name not in values:
        return default
    raw = _clean(values[name])
    if raw is None:
        errors[name] = "não pode ser vazio"
        return default
    try:
        return int(raw)
    except ValueError:
        errors[name] = "deve ser um número inteiro"
        return default


def _parse_float(
    values: Mapping[str, object], name: str, default: float, errors: dict[str, str]
) -> float:
    if name not in values:
        return default
    raw = _clean(values[name])
    if raw is None:
        errors[name] = "não pode ser vazio"
        return default
    try:
        value = float(raw)
    except ValueError:
        errors[name] = "deve ser um número"
        return default
    if not math.isfinite(value):
        errors[name] = "deve ser um número finito"
        return default
    return value


def _parse_bool(
    values: Mapping[str, object], name: str, default: bool, errors: dict[str, str]
) -> bool:
    if name not in values:
        return default
    raw = _clean(values[name])
    if raw is None:
        errors[name] = "use true ou false"
        return default
    normalized = raw.casefold()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    errors[name] = "use true ou false"
    return default


def load_settings(
    environ: Mapping[str, str] | None = None,
    *,
    env_file: str | Path | None | _DefaultEnvFile = _DEFAULT_ENV_FILE,
) -> Settings:
    """Carrega settings novos sem cache, útil para testes e recarga explícita.

    Um ambiente injetado é isolado por padrão. Sem ``environ``, o processo
    prevalece sobre o .env local. ``APP_ENV=test`` nunca lê o arquivo padrão.
    """
    process_values = dict(os.environ if environ is None else environ)
    if env_file is _DEFAULT_ENV_FILE:
        selected_env_file: str | Path | None = ENV_FILE if environ is None else None
    else:
        selected_env_file = env_file

    process_app_env = _clean(process_values.get("APP_ENV"))
    if process_app_env and process_app_env.casefold() == "test":
        selected_env_file = None

    file_values: dict[str, str | None] = {}
    if selected_env_file is not None:
        # Sem interpolação implícita: testes injetados não herdam valores de os.environ.
        file_values = dotenv_values(selected_env_file, interpolate=False)

    values: dict[str, object] = dict(file_values)
    values.update(process_values)
    provided_names = frozenset(name for name in values if name in _ALL_SETTING_NAMES)
    errors: dict[str, str] = {}

    raw_app_env = _clean(values.get("APP_ENV"))
    app_env = (raw_app_env or "development").casefold()
    app_env_error = ("APP_ENV" in values and raw_app_env is None) or app_env not in _ENVIRONMENTS
    if app_env_error:
        errors["APP_ENV"] = "use development, test, staging ou production"

    split_values = {name: _clean(values.get(name)) for name in _POSTGRES_SPLIT_NAMES}
    split_requested = any(name in provided_names for name in _POSTGRES_SPLIT_NAMES)
    local_defaults = app_env == "development"

    database_url = _clean(values.get("DATABASE_URL"))
    if database_url is None and local_defaults and not split_requested:
        database_url = "postgresql://postgres:postgres@localhost:5432/postgres"

    mongo_app_uri = _clean(values.get("MONGODB_APP_URI"))
    mongo_telemetry_uri = _clean(values.get("MONGODB_TELEMETRY_URI"))
    if local_defaults:
        if "MONGODB_APP_URI" not in values:
            mongo_app_uri = "mongodb://localhost:27018"
        if "MONGODB_TELEMETRY_URI" not in values:
            mongo_telemetry_uri = "mongodb://localhost:27018"

    return Settings(
        app_env=app_env,
        gemini_api_key=_clean(values.get("GEMINI_API_KEY")),
        groq_api_key=_clean(values.get("GROQ_API_KEY")),
        database_url=database_url,
        host_db=split_values["HOST_DB"],
        port_db=split_values["PORT_DB"],
        user_db=split_values["USER_DB"],
        password_db=values.get("PASSWORD_DB") if _has_text(split_values["PASSWORD_DB"]) else None,
        name_db=split_values["NAME_DB"],
        mongodb_app_uri=mongo_app_uri,
        mongodb_telemetry_uri=mongo_telemetry_uri,
        mongo_db_app=_string_setting(values, "MONGO_DB_APP", "db_delta_app"),
        mongo_db_telemetry=_string_setting(values, "MONGO_DB_TELEMETRY", "db_delta_telemetry"),
        gemini_model=_string_setting(values, "GEMINI_MODEL", "gemini-2.5-flash"),
        groq_specialist_model=_string_setting(
            values, "GROQ_SPECIALIST_MODEL", "openai/gpt-oss-120b"
        ),
        groq_fast_model=_string_setting(values, "GROQ_FAST_MODEL", "openai/gpt-oss-20b"),
        llm_fallback_enabled=_parse_bool(values, "LLM_FALLBACK_ENABLED", True, errors),
        llm_timeout_seconds=_parse_float(values, "LLM_TIMEOUT_SECONDS", 15.0, errors),
        llm_max_retries=_parse_int(values, "LLM_MAX_RETRIES", 1, errors),
        llm_max_output_tokens=_parse_int(values, "LLM_MAX_OUTPUT_TOKENS", 4096, errors),
        db_connect_timeout_seconds=_parse_int(values, "DB_CONNECT_TIMEOUT_SECONDS", 5, errors),
        db_query_timeout_seconds=_parse_int(values, "DB_QUERY_TIMEOUT_SECONDS", 30, errors),
        _provided_names=provided_names,
        _parse_errors=tuple(errors.items()),
        _app_env_error=app_env_error,
    )


@lru_cache(maxsize=1)
def _cached_settings() -> Settings:
    return load_settings()


# Constantes públicas mantidas para compatibilidade com imports existentes.
def _sync_legacy_constants(settings: Settings) -> None:
    globals().update(
        {
            "APP_ENV": settings.app_env,
            "GEMINI_API_KEY": settings.gemini_api_key or "",
            "GROQ_API_KEY": settings.groq_api_key or "",
            "DATABASE_URL": settings.database_url or "",
            "HOST_DB": settings.host_db,
            "PORT_DB": settings.port_db,
            "USER_DB": settings.user_db,
            "PASSWORD_DB": settings.password_db,
            "NAME_DB": settings.name_db,
            "MONGODB_APP_URI": settings.mongodb_app_uri or "",
            "MONGODB_TELEMETRY_URI": settings.mongodb_telemetry_uri or "",
            "MONGO_DB_APP": settings.mongo_db_app,
            "MONGO_DB_TELEMETRY": settings.mongo_db_telemetry,
        }
    )


def get_settings(*, refresh: bool = False) -> Settings:
    """Retorna o snapshot em cache; ``refresh=True`` recarrega processo e .env."""
    if refresh:
        _cached_settings.cache_clear()
    settings = _cached_settings()
    _sync_legacy_constants(settings)
    return settings


def clear_settings_cache() -> None:
    """Limpa o snapshot para testes que alteraram o ambiente do processo."""
    _cached_settings.cache_clear()


def reload_settings() -> Settings:
    """Recarrega settings e atualiza as constantes públicas de compatibilidade."""
    return get_settings(refresh=True)


def _problems_for_names(settings: Settings, names: set[str]) -> list[str]:
    problems = [f"{name}: {message}" for name, message in settings._parse_errors if name in names]
    if settings._app_env_error:
        problems.append("APP_ENV: use development, test, staging ou production")
    return problems


def _raise_if_invalid(component: str, problems: list[str]) -> None:
    if problems:
        raise ConfigurationError(f"Configuração {component} inválida: {', '.join(problems)}.")


def validate_llm_config(
    provider: Literal["specialist", "gemini", "groq_specialist", "fast"] = "specialist",
    *,
    settings: Settings | None = None,
) -> None:
    """Valida somente chaves e parâmetros do caminho LLM selecionado."""
    current = settings or get_settings()
    if provider not in {"specialist", "gemini", "groq_specialist", "fast"}:
        raise ValueError("provider deve ser specialist, gemini, groq_specialist ou fast")

    needs_gemini = provider in {"specialist", "gemini"}
    needs_groq = provider in {"groq_specialist", "fast"} or (
        provider == "specialist" and current.llm_fallback_enabled
    )
    names = {"LLM_TIMEOUT_SECONDS", "LLM_MAX_RETRIES", "LLM_MAX_OUTPUT_TOKENS"}
    if provider == "specialist":
        names.add("LLM_FALLBACK_ENABLED")
    if needs_gemini:
        names.add("GEMINI_API_KEY")
    if needs_groq:
        names.add("GROQ_API_KEY")
    problems = _problems_for_names(current, names)

    required_values: list[tuple[str, str | None]] = []
    if needs_gemini:
        required_values.extend(
            [("GEMINI_API_KEY", current.gemini_api_key), ("GEMINI_MODEL", current.gemini_model)]
        )
    if needs_groq:
        model = current.groq_fast_model if provider == "fast" else current.groq_specialist_model
        model_name = "GROQ_FAST_MODEL" if provider == "fast" else "GROQ_SPECIALIST_MODEL"
        required_values.extend([("GROQ_API_KEY", current.groq_api_key), (model_name, model)])

    for name, value in required_values:
        if not _has_text(value):
            problems.append(f"{name} ausente ou vazio")
    if current.llm_timeout_seconds <= 0:
        problems.append("LLM_TIMEOUT_SECONDS deve ser positivo")
    if current.llm_max_retries < 0:
        problems.append("LLM_MAX_RETRIES não pode ser negativo")
    if current.llm_max_output_tokens <= 0:
        problems.append("LLM_MAX_OUTPUT_TOKENS deve ser positivo")
    _raise_if_invalid("LLM", problems)


def validate_postgres_config(*, settings: Settings | None = None) -> None:
    """Valida PostgreSQL sem abrir conexão."""
    current = settings or get_settings()
    names = set(_POSTGRES_SPLIT_NAMES) | {
        "DATABASE_URL",
        "DB_CONNECT_TIMEOUT_SECONDS",
        "DB_QUERY_TIMEOUT_SECONDS",
    }
    problems = _problems_for_names(current, names)

    if current.postgres_split_requested:
        missing = [
            name
            for name in _POSTGRES_SPLIT_NAMES
            if not _has_text(getattr(current, name.lower()))
        ]
        if missing:
            problems.append("configuração separada incompleta: " + ", ".join(missing))
        else:
            try:
                port = int(current.port_db or "")
                if not 1 <= port <= 65535:
                    raise ValueError
            except ValueError:
                problems.append("PORT_DB deve estar entre 1 e 65535")
    elif not _has_text(current.database_url):
        problems.append("DATABASE_URL ausente")
    else:
        try:
            parsed = urlsplit(current.database_url or "")
            port = parsed.port
            valid = (
                parsed.scheme in {"postgres", "postgresql"}
                and bool(parsed.hostname)
                and bool(parsed.path.strip("/"))
                and (port is None or 1 <= port <= 65535)
            )
        except ValueError:
            valid = False
        if not valid:
            problems.append("DATABASE_URL deve ser uma URI PostgreSQL válida")

    if current.db_connect_timeout_seconds <= 0:
        problems.append("DB_CONNECT_TIMEOUT_SECONDS deve ser positivo")
    if current.db_query_timeout_seconds <= 0:
        problems.append("DB_QUERY_TIMEOUT_SECONDS deve ser positivo")
    _raise_if_invalid("PostgreSQL", problems)


def validate_mongo_config(
    component: Literal["app", "telemetry"] = "app",
    *,
    settings: Settings | None = None,
) -> None:
    """Valida uma URI Mongo por vez, sem validar chaves de LLM."""
    current = settings or get_settings()
    if component not in {"app", "telemetry"}:
        raise ValueError("component deve ser app ou telemetry")

    if component == "app":
        uri, uri_name = current.mongodb_app_uri, "MONGODB_APP_URI"
        database, database_name = current.mongo_db_app, "MONGO_DB_APP"
    else:
        uri, uri_name = current.mongodb_telemetry_uri, "MONGODB_TELEMETRY_URI"
        database, database_name = current.mongo_db_telemetry, "MONGO_DB_TELEMETRY"

    names = {uri_name, database_name, "DB_CONNECT_TIMEOUT_SECONDS", "DB_QUERY_TIMEOUT_SECONDS"}
    problems = _problems_for_names(current, names)
    if not _has_text(uri):
        problems.append(f"{uri_name} ausente ou vazio")
    else:
        try:
            parsed = urlsplit(uri or "")
            port = parsed.port
            valid = (
                parsed.scheme in {"mongodb", "mongodb+srv"}
                and bool(parsed.hostname)
                and (port is None or 1 <= port <= 65535)
                and not (parsed.scheme == "mongodb+srv" and port is not None)
            )
        except ValueError:
            valid = False
        if not valid:
            problems.append(f"{uri_name} deve ser uma URI MongoDB válida")
    if not _has_text(database):
        problems.append(f"{database_name} vazio")
    if current.db_connect_timeout_seconds <= 0:
        problems.append("DB_CONNECT_TIMEOUT_SECONDS deve ser positivo")
    if current.db_query_timeout_seconds <= 0:
        problems.append("DB_QUERY_TIMEOUT_SECONDS deve ser positivo")
    _raise_if_invalid("MongoDB", problems)


def get_postgres_connection_args(*, settings: Settings | None = None) -> dict[str, object]:
    """Retorna argumentos do psycopg2 após validar as configurações."""
    current = settings or get_settings()
    validate_postgres_config(settings=current)
    args: dict[str, object] = {"connect_timeout": current.db_connect_timeout_seconds}
    if current.postgres_split_requested:
        args.update(
            host=current.host_db,
            port=int(current.port_db or ""),
            user=current.user_db,
            password=current.password_db,
            dbname=current.name_db,
        )
    else:
        # A URI integral preserva opções de TLS e a codificação da senha.
        args["dsn"] = current.database_url
    return args


def validate_config() -> list[str]:
    """Mantém a API antiga de diagnóstico, agregando erros dos componentes."""
    current = get_settings()
    checks = (
        lambda: validate_llm_config("specialist", settings=current),
        lambda: validate_llm_config("fast", settings=current),
        lambda: validate_postgres_config(settings=current),
        lambda: validate_mongo_config("app", settings=current),
        lambda: validate_mongo_config("telemetry", settings=current),
    )
    problems: list[str] = []
    for check in checks:
        try:
            check()
        except ConfigurationError as error:
            problems.append(str(error))
    return problems


_sync_legacy_constants(get_settings())
