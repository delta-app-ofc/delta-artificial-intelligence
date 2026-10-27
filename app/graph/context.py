from __future__ import annotations

from time import perf_counter

from app.memory.session import load_history_validated
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
    trace = current_trace()
    question_lower = question.lower()
    if not any(trigger in question_lower for trigger in _MEMORY_TRIGGERS):
        if trace:
            trace.event(
                "context.phase.end",
                component="context",
                operation="long_term_memory",
                status="skipped",
                metadata={"phase": "long_term_memory", "outcome": "not_requested"},
            )
        return []

    started = perf_counter()
    errors_before = len(trace.errors) if trace else 0
    if trace:
        trace.event(
            "context.phase.start",
            component="context",
            operation="long_term_memory",
            status="running",
            metadata={"phase": "long_term_memory"},
        )
    try:
        from app.memory.long_term import search_memory
        results = search_memory(user_id, question)
    except Exception as error:
        record = trace.error(
            "long_term_memory",
            error,
            operation="search_memory",
            metadata={"phase": "long_term_memory"},
        ) if trace else None
        if trace:
            trace.event(
                "context.phase.end",
                component="context",
                operation="long_term_memory",
                status="unavailable",
                duration_ms=round((perf_counter() - started) * 1000, 1),
                metadata={
                    "phase": "long_term_memory",
                    "outcome": "unavailable",
                    **({"error_id": record["error_id"]} if record else {}),
                },
            )
        return []

    if trace:
        failed = len(trace.errors) > errors_before
        trace.event(
            "context.phase.end",
            component="context",
            operation="long_term_memory",
            status="partial" if failed else "success",
            duration_ms=round((perf_counter() - started) * 1000, 1),
            metadata={
                "phase": "long_term_memory",
                "outcome": "unavailable" if failed else "retrieved" if results else "empty",
            },
        )
    return results


def build_context(user_id: int, session_id: str, question: str) -> dict:
    """Monta histórico validado da sessão e memória de longo prazo para o roteador."""
    trace = current_trace()
    started = perf_counter()
    if trace:
        trace.event(
            "context.phase.start",
            component="context",
            operation="session_history",
            status="running",
            metadata={"phase": "session_history"},
        )
    try:
        history = load_history_validated(user_id, session_id)
    except Exception as error:
        record = trace.error(
            "session_history",
            error,
            operation="load_history",
            metadata={"phase": "session_history"},
        ) if trace else None
        if trace:
            trace.event(
                "context.phase.end",
                component="context",
                operation="session_history",
                status="unavailable",
                duration_ms=round((perf_counter() - started) * 1000, 1),
                metadata={
                    "phase": "session_history",
                    "outcome": "unavailable",
                    **({"error_id": record["error_id"]} if record else {}),
                },
            )
        history = []
    else:
        if trace:
            trace.event(
                "context.phase.end",
                component="context",
                operation="session_history",
                status="success",
                duration_ms=round((perf_counter() - started) * 1000, 1),
                metadata={
                    "phase": "session_history",
                    "outcome": "loaded" if history else "empty",
                },
            )
    recent = [
        {"role": item["role"], "content": item["content"]}
        for item in history[-RECENT_TURNS:]
        if item.get("role") in ("human", "assistant")
    ]
    return {
        "recent_messages": recent,
        "relevant_memory": find_relevant_memory(user_id, question),
    }