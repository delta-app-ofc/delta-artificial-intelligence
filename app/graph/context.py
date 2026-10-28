from __future__ import annotations

from app.memory.session import load_history_validated, to_chat_messages
from app.observability.diagnostics import current_trace

RECENT_TURNS = 6

_MEMORY_TRIGGERS = {
    "antes", "anterior", "anteriormente", "última vez", "últimas semanas", "últimos meses",
    "semana passada", "mês passado", "na semana passada", "no mês passado", "na última",
    "você disse", "você me disse", "você falou", "você comentou", "você mencionou",
    "lembra", "lembro", "lembre", "você lembra", "você se lembra",
    "histórico", "já falamos", "já conversamos", "já discutimos",
    "discutimos", "como combinamos", "como você disse", "como falamos",
}


def find_relevant_memory(user_id: int, question: str) -> list[str]:
    """Busca resumos de sessões anteriores quando a pergunta pede contexto do passado."""
    question_lower = question.lower()
    if not any(trigger in question_lower for trigger in _MEMORY_TRIGGERS):
        return []
    try:
        from app.memory.long_term import search_memory
        return search_memory(user_id, question)
    except Exception as error:
        if trace := current_trace():
            trace.error("long_term_memory", error)
        return []


def build_context(user_id: int, session_id: str, question: str) -> dict:
    """Monta histórico validado da sessão e memória de longo prazo para o roteador."""
    try:
        history = load_history_validated(user_id, session_id)
    except Exception as error:
        if trace := current_trace():
            trace.error("session_history", error)
        history = []
    recent = to_chat_messages(history[-RECENT_TURNS:])
    return {
        "recent_messages": recent,
        "relevant_memory": find_relevant_memory(user_id, question),
    }