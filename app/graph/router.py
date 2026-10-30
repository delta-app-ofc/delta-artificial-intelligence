from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel

from app.config import ConfigurationError
from app.agents._runtime import _message_text
from app.observability.diagnostics import current_trace
from app.services.prompts import ROUTER_PROMPT

AGENT_REGISTRY: dict[str, str] = {
    "consumption": "app.agents.consumption.ConsumptionAgent",
    "forecast": "app.agents.forecast.ForecastAgent",
    "leak": "app.agents.leak.LeakAgent",
    "habits": "app.agents.habits.HabitsAgent",
    "rag": "app.agents.rag.RagAgent",
}


class AgentNotImplemented(RuntimeError):
    """Agente reservado; ainda não existe implementação para executar."""


class RoutingDecision(BaseModel):
    intent: str
    complexity: Literal["simple", "medium", "complex"]
    agents: list[str]


def classify(question: str, context: dict) -> RoutingDecision:
    import app.services.llms as _llm_module
    from langchain_core.messages import HumanMessage, SystemMessage

    ctx_lines: list[str] = []
    recent = context.get("recent_messages", [])
    if recent:
        turns = "\n".join(f"  {message['role']}: {message['content']}"
                           for message in recent[-4:])
        ctx_lines.append(f"Histórico recente:\n{turns}")
    memory = context.get("relevant_memory", [])
    if memory:
        ctx_lines.append(f"Memórias relevantes: {'; '.join(memory[:2])}")
    context_text = "\n".join(ctx_lines)
    user_text = f"{context_text}\n\nPergunta: {question}" if context_text else question

    try:
        llm = _llm_module.llm_rapido
        if llm is None:
            raise ConfigurationError("Configure o provedor de linguagem selecionado para o roteador.")
        response = llm.invoke(
            [SystemMessage(content=ROUTER_PROMPT), HumanMessage(content=user_text)]
        )
        content = _message_text(response) if hasattr(response, "content") else str(response)
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            start = content.find("{")
            end = content.rfind("}") + 1
            data = json.loads(content[start:end]) if start >= 0 and end > start else {}
        decision = RoutingDecision(**data)
        known = set(AGENT_REGISTRY)
        if trace := current_trace():
            trace.skipped_agents.extend(name for name in decision.agents if name not in known)
        decision.agents = list(dict.fromkeys(name for name in decision.agents if name in known))
        return decision
    except Exception as error:
        if trace := current_trace():
            trace.error("router", error)
    return RoutingDecision(intent="unknown", complexity="simple", agents=[])


def load_agent(name: str, user_id: int):
    """Instancia um especialista e diferencia implementações pendentes."""
    import importlib

    module_path, class_name = AGENT_REGISTRY[name].rsplit(".", 1)
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name, None)
    if cls is None or not callable(getattr(cls, "run", None)):
        raise AgentNotImplemented(name)
    return cls(user_id=user_id)
