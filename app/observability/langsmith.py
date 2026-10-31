"""Liga o tracing opcional do LangSmith a partir das variáveis LANGSMITH_*."""
from __future__ import annotations

import os

from dotenv import dotenv_values

from app.config import BASE_DIR

_NAMES = ("LANGSMITH_TRACING", "LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_ENDPOINT")


def enable_langsmith() -> bool:
    """Copia LANGSMITH_* do .env para o processo e devolve se o tracing ficou ativo.

    O LangChain lê essas variáveis direto de os.environ. Em APP_ENV=test o .env é
    ignorado, como no resto da configuração; a chave nunca é registrada em log.
    """
    if (os.environ.get("APP_ENV") or "").strip().casefold() != "test":
        file_values = dotenv_values(BASE_DIR / ".env", interpolate=False)
        for name in _NAMES:
            value = (file_values.get(name) or "").strip()
            if value and not os.environ.get(name):
                os.environ[name] = value
    tracing = (os.environ.get("LANGSMITH_TRACING") or "").strip().casefold() == "true"
    return tracing and bool(os.environ.get("LANGSMITH_API_KEY"))
