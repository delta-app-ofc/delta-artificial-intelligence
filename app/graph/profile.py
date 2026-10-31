"""Perfil de acesso do usuário: define quais agentes e respostas fixas valem para cada um."""

from __future__ import annotations

from app.data import db_postgres
from app.observability.diagnostics import current_trace

# Sem vínculo ("none") ou perfil não identificado ("unknown", banco fora): nenhum agente roda;
# a pergunta cai sempre na mensagem de orientação, sem depender do roteador.
AGENTS_BY_PROFILE: dict[str, frozenset[str]] = {
    "residential": frozenset({"consumption", "forecast", "leak", "habits", "rag"}),
    "organizational": frozenset({"consumption", "forecast", "leak", "rag"}),
    "none": frozenset(),
    "unknown": frozenset(),
}

_UNAVAILABLE_AGENT_MESSAGES = {
    "habits": (
        "Hábitos de consumo estão disponíveis apenas para contas residenciais. "
        "Posso ajudar com o consumo, a previsão e os vazamentos das suas unidades."
    ),
}

_GREETINGS = {
    "residential": (
        "Oi! Posso ajudar com seu consumo de água, previsões, alertas e hábitos. "
        "O que você gostaria de saber?"
    ),
    "organizational": (
        "Oi! Posso ajudar com o consumo das suas unidades, previsões e alertas de vazamento. "
        "O que você gostaria de saber?"
    ),
    "none": (
        "Oi! Sua conta ainda não está vinculada a uma residência ou organização, então não consigo "
        "consultar dados de consumo. Vincule sua conta para eu poder ajudar."
    ),
    "unknown": "Oi! Não consegui identificar o perfil da sua conta agora. Tente novamente em instantes.",
}

_NO_AGENT_RESPONSES = {
    "residential": (
        "Não entendi o que você gostaria de saber. Posso ajudar com previsão de consumo, "
        "detecção de vazamentos ou seus hábitos de água."
    ),
    "organizational": (
        "Não entendi o que você gostaria de saber. Posso ajudar com o consumo, a previsão "
        "e a detecção de vazamentos das suas unidades."
    ),
    "none": (
        "Sua conta ainda não está vinculada a uma residência ou organização, então não consigo "
        "consultar dados. Vincule sua conta para eu poder ajudar."
    ),
    "unknown": "Não consegui identificar o perfil da sua conta agora. Tente novamente em instantes.",
}


def resolve_access_kind(user_id: int) -> str:
    """Descobre o perfil uma vez por pergunta; falha do banco vira "unknown", nunca um perfil assumido."""
    try:
        return db_postgres.get_user_access_kind(user_id)
    except Exception as error:
        if trace := current_trace():
            trace.error("profile", error)
        return "unknown"


def allowed_agents(access_kind: str | None) -> frozenset[str] | None:
    """Agentes liberados para o perfil; None (perfil não informado) mantém todos; vazio = nenhum."""
    if access_kind is None:
        return None
    return AGENTS_BY_PROFILE.get(access_kind, AGENTS_BY_PROFILE["unknown"])


def unavailable_agent_message(agent_names: list[str]) -> str | None:
    """Explica por que um agente pedido não vale para o perfil, quando há texto para ele."""
    for name in agent_names:
        if name in _UNAVAILABLE_AGENT_MESSAGES:
            return _UNAVAILABLE_AGENT_MESSAGES[name]
    return None


def greeting_response(access_kind: str | None) -> str:
    return _GREETINGS.get(access_kind or "residential", _GREETINGS["unknown"])


def no_agent_response(access_kind: str | None) -> str:
    return _NO_AGENT_RESPONSES.get(access_kind or "residential", _NO_AGENT_RESPONSES["unknown"])
