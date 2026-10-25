"""Criação lazy do classificador TypeSafe usado pelo Agente Juiz."""

from __future__ import annotations

from app.config import get_settings, validate_jev_config


def create_jev_classifier():
    """Cria o cliente Jev depois de validar as configurações locais."""
    settings = get_settings()
    validate_jev_config(settings=settings)

    from langchain_typesafe import TypeSafeClassifier

    return TypeSafeClassifier(
        model=settings.jev_model,
        api_key=settings.typesafe_api_key,
        timeout=settings.jev_timeout_seconds,
    )
