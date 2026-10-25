from __future__ import annotations

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


def find_relevant_memory(user_id: int, question: str) -> list[str]:
    """Busca resumos de sessões anteriores, só se a pergunta se refere ao passado.

    Evita embedding + busca vetorial em todo request sem necessidade.
    """
    question_lower = question.lower()
    if not any(trigger in question_lower for trigger in _MEMORY_TRIGGERS):
        return []

    try:
        from app.memory.long_term import search_memory

        return search_memory(user_id, question)
    except Exception:
        return []
