"""Criação lazy do classificador TypeSafe usado pelo Agente Juiz."""

from __future__ import annotations

from functools import lru_cache

from app.config import get_settings, validate_jev_config


@lru_cache(maxsize=1)
def create_jev_classifier():
    """Reutiliza o cliente Jev após validar a configuração no primeiro uso."""
    settings = get_settings()
    validate_jev_config(settings=settings)

    from langchain_typesafe import TypeSafeClassifier

    return TypeSafeClassifier(
        model=settings.jev_model,
        api_key=settings.typesafe_api_key,
        timeout=settings.jev_timeout_seconds,
    )
