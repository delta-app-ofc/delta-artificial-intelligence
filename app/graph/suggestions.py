"""Sugestões de próximas perguntas, escolhidas por regra (sem LLM e sem custo)."""

from __future__ import annotations

MAX_SUGGESTIONS = 3

_BY_AGENT = {
    "consumption": [
        "Qual foi o meu pico de consumo neste mês?",
        "Como foi meu consumo comparado com o mês passado?",
    ],
    "forecast": [
        "E se meu consumo diário cair 10%?",
        "Vou ultrapassar minha meta neste mês?",
    ],
    "leak": [
        "Há algum sinal de vazamento nos últimos dias?",
        "O que significa um indício de vazamento?",
    ],
    "habits": [
        "Quanto eu gastaria se lavasse roupa 3 vezes por semana?",
        "Quais hábitos tenho cadastrados?",
    ],
    "rag": [
        "Como vinculo meu hidrômetro?",
        "Quais práticas ajudam a economizar água?",
    ],
}

_ORGANIZATIONAL = {
    "consumption": [
        "Qual unidade consumiu mais neste mês?",
        "Como foi o consumo das unidades comparado com o mês passado?",
    ],
    "forecast": [
        "E se o consumo diário das unidades cair 10%?",
        "Qual é a estimativa da próxima conta?",
    ],
    "leak": ["Há algum sinal de vazamento nas minhas unidades?"],
}

_START = {
    "residential": [
        "Quanto consumi esta semana?",
        "Quanto vou gastar este mês?",
        "Quanto eu gastaria se lavasse roupa 3 vezes por semana?",
    ],
    "organizational": [
        "Quanto minhas unidades consumiram esta semana?",
        "Qual é a estimativa da próxima conta?",
        "Há algum sinal de vazamento nas minhas unidades?",
    ],
}


def initial_suggestions(access_kind: str | None) -> list[str]:
    """Perguntas para começar a conversa; perfil desconhecido usa as residenciais."""
    return list(_START.get(access_kind or "residential", _START["residential"]))


def suggest_next_questions(
    agents: list[str], access_kind: str | None, asked: str = ""
) -> list[str]:
    """Até três perguntas ligadas aos assuntos já tratados, sem repetir a que acabou de ser feita.

    Hábitos só existem para conta residencial. Sem agentes (saudação, por exemplo), devolve as
    perguntas iniciais do perfil.
    """
    organizational = access_kind == "organizational"
    asked_key = asked.strip().casefold()
    pool: list[str] = []
    for agent in agents or []:
        if organizational:
            pool += _ORGANIZATIONAL.get(agent, [])
        else:
            pool += _BY_AGENT.get(agent, [])
    if not pool:
        pool = initial_suggestions(access_kind)
    result: list[str] = []
    for question in pool:
        if question.casefold() != asked_key and question not in result:
            result.append(question)
    return result[:MAX_SUGGESTIONS]
