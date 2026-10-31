from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from app.services.prompts import SYNTHESIS_PROMPT, profile_block
from app.agents._runtime import _message_text
from app.observability.diagnostics import current_trace


def synthesize(question: str, answers: list[dict], access_kind: str | None = None) -> dict | None:
    """Une as respostas dos agentes num texto só, com o LLM rápido.

    Devolve {"response", "chart_data"} ou None se o LLM não estiver disponível ou falhar.
    """
    import app.services.llms as llms

    llm = llms.llm_rapido
    if llm is None:
        return None

    answers_text = "\n\n".join(f"[{a['agent'].upper()}]\n{a['answer']}" for a in answers)
    prompt = SYNTHESIS_PROMPT.format(n=len(answers), question=question, respostas=answers_text)
    prompt += profile_block(access_kind)

    try:
        response = llm.invoke(
            [SystemMessage(content=prompt), HumanMessage(content="Unifique as respostas.")]
        )
    except Exception as error:
        if trace := current_trace():
            trace.error("synthesis", error, operation="combine_answers")
        return None

    unified = _message_text(response) if hasattr(response, "content") else str(response)
    if not unified.strip():
        return None

    chart_data = next((a["chart_data"] for a in answers if a.get("chart_data")), None)
    return {"response": unified.strip(), "chart_data": chart_data}
