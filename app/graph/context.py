from __future__ import annotations

RECENT_TURNS = 6

# Palavras que indicam que o usuário quer contexto de sessões anteriores.
# Apenas nesse caso vale o custo de embedding + busca Qdrant.
_MEMORY_TRIGGERS = {
    "antes", "anterior", "anteriormente", "última vez", "últimas semanas", "últimos meses",
    "semana passada", "mês passado", "na semana passada", "no mês passado", "na última",
    "você disse", "você me disse", "você falou", "você comentou", "você mencionou",
    "lembra", "lembro", "lembre", "você lembra", "você se lembra",
    "histórico", "já falamos", "já conversamos", "já discutimos",
    "discutimos", "como combinamos", "como você disse", "como falamos",
}


def _needs_long_term_memory(question: str) -> bool:
    q = question.lower()
    return any(trigger in q for trigger in _MEMORY_TRIGGERS)


def build_context(user_id: int, session_id: str, question: str) -> dict:
    """Monta contexto consolidado para o Router.

    Sempre recupera histórico recente (MongoDB, rápido).
    Só chama Qdrant quando a pergunta indica referência a sessões anteriores —
    evitar embedding + busca vetorial em todo request sem necessidade.
    """
    from app.memory.session import load_history_validated

    try:
        recent = load_history_validated(user_id, session_id)
    except Exception:
        recent = []

    relevant: list[str] = []
    if _needs_long_term_memory(question):
        try:
            from app.memory.long_term import search_memory
            relevant = search_memory(user_id, question)
        except Exception:
            relevant = []

    return {
        "recent_messages": recent[-RECENT_TURNS:],
        "relevant_memory": relevant,
    }
