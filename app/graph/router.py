from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel

from app.services.prompts import ROUTER_PROMPT

AGENT_REGISTRY: dict[str, str] = {
    "consumption": "app.agents.consumption.ConsumptionAgent",
    "forecast": "app.agents.forecast.ForecastAgent",
    "leak": "app.agents.leak.LeakAgent",
    "habits": "app.agents.habits.HabitsAgent",
    "rag": "app.agents.rag.RagAgent",
}


class RoutingDecision(BaseModel):
    intent: str
    complexity: Literal["simple", "medium", "complex"]
    agents: list[str]


def classify(question: str, context: dict) -> RoutingDecision:
    import app.services.llms as _llm_module
    from langchain_core.messages import HumanMessage, SystemMessage

    llm_rapido = _llm_module.llm_rapido

    ctx_lines: list[str] = []
    recent = context.get("recent_messages", [])
    if recent:
        turns = "\n".join(f"  {m['role']}: {m['content']}" for m in recent[-4:])
        ctx_lines.append(f"Histórico recente:\n{turns}")
    memory = context.get("relevant_memory", [])
    if memory:
        ctx_lines.append(f"Memórias relevantes: {'; '.join(memory[:2])}")

    ctx_text = "\n".join(ctx_lines)
    user_text = f"{ctx_text}\n\nPergunta: {question}" if ctx_text else question

    try:
        response = llm_rapido.invoke(
            [SystemMessage(content=ROUTER_PROMPT), HumanMessage(content=user_text)]
        )
        content = response.content if hasattr(response, "content") else str(response)
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            start = content.find("{")
            end = content.rfind("}") + 1
            data = json.loads(content[start:end]) if start >= 0 and end > start else {}
        decision = RoutingDecision(**data)
        known = set(AGENT_REGISTRY)
        decision.agents = [a for a in decision.agents if a in known]
        return decision
    except Exception:
        pass

    return RoutingDecision(intent="unknown", complexity="simple", agents=[])


def load_agent(name: str, user_id: int):
    """Instancia o agente pelo nome, consultando AGENT_REGISTRY."""
    import importlib

    module_path, class_name = AGENT_REGISTRY[name].rsplit(".", 1)
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls(user_id=user_id)
