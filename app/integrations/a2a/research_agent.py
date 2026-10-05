"""Cliente A2A do agente de pesquisa externo.

Implementa o protocolo A2A (Agent-to-Agent):
1. Descoberta: GET {url}/.well-known/agent.json
2. Envio de tarefa: POST {url}/tasks/send
3. Leitura do resultado: task.status.message.parts[0].text
"""

from __future__ import annotations

import uuid

from langchain_core.tools import tool

from app.config import A2A_RESEARCH_AGENT_URL


def _discover(base_url: str) -> dict | None:
    """Baixa o agent card do agente remoto."""
    import httpx

    try:
        r = httpx.get(f"{base_url}/.well-known/agent.json", timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _send_task(base_url: str, query: str) -> dict:
    """Envia uma tarefa A2A e retorna o resultado."""
    import httpx

    payload = {
        "id": str(uuid.uuid4()),
        "message": {
            "role": "user",
            "parts": [{"type": "text", "text": query}],
        },
    }
    r = httpx.post(f"{base_url}/tasks/send", json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


def _extract_text(task_result: dict) -> str:
    try:
        parts = task_result["status"]["message"]["parts"]
        for part in parts:
            if part.get("type") == "text":
                return part["text"]
    except (KeyError, TypeError):
        pass
    return str(task_result)


@tool
def research_water_topic(query: str) -> dict:
    """Pesquisa um tópico relacionado a água (tecnologia, conservação, regulação etc.)
    delegando a um agente externo via protocolo A2A.

    Use quando o usuário fizer perguntas de pesquisa geral sobre água que não
    sejam sobre consumo, vazamento ou hábitos específicos do usuário.

    query: pergunta ou tema a pesquisar (ex.: 'como funciona um hidrômetro?').
    """
    if not A2A_RESEARCH_AGENT_URL:
        return {
            "status": "error",
            "message": "A2A_RESEARCH_AGENT_URL não configurado no .env.",
        }

    try:
        result = _send_task(A2A_RESEARCH_AGENT_URL, query)
        return {"status": "ok", "answer": _extract_text(result)}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}
