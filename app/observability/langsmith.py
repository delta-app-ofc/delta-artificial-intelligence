"""Liga o tracing opcional do LangSmith a partir dos settings."""
from __future__ import annotations

import os

from app.config import get_observability_config


def enable_langsmith() -> bool:
    """Exporta os settings LANGSMITH_* validados e devolve se o tracing ficou ativo.

    O LangChain só lê o LangSmith de os.environ, por isso o valor já validado em
    app/config.py é copiado para lá. A chave nunca é registrada em log.
    """
    settings = get_observability_config()
    if not (settings.langsmith_tracing and settings.langsmith_api_key):
        return False
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    # Por padrão só métricas (tokens, custo, tempo) vão ao LangSmith: prompts e respostas podem ter dados pessoais.
    hide = "false" if settings.langsmith_send_content else "true"
    os.environ["LANGSMITH_HIDE_INPUTS"] = hide
    os.environ["LANGSMITH_HIDE_OUTPUTS"] = hide
    return True
