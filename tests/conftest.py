"""Mantém a suíte isolada do .env e das credenciais do processo local."""

import os

_SETTING_NAMES = (
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "DATABASE_URL",
    "HOST_DB",
    "PORT_DB",
    "USER_DB",
    "PASSWORD_DB",
    "NAME_DB",
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
)
for _name in _SETTING_NAMES:
    os.environ.pop(_name, None)
os.environ["APP_ENV"] = "test"

import pytest

from app.config import clear_settings_cache, get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache_after_test():
    yield
    clear_settings_cache()
    get_settings()
