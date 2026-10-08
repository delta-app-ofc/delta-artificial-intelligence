from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel

AGENT_REGISTRY: dict[str, str] = {
    "forecast": "app.agents.forecast.ForecastAgent",
    "leak": "app.agents.leak.LeakAgent",
    "habits": "app.agents.habits.HabitsAgent",
}

_ROUTER_PROMPT = """Você é o roteador do Delta AI, assistente de monitoramento de consumo de água.
Classifique a pergunta e decida quais agentes devem responder.

Agentes disponíveis:
- forecast: previsão de consumo, estimativa da próxima conta, tendência, risco de meta
- leak: possíveis vazamentos, consumo anormal, alertas de comportamento atípico
- habits: hábitos cadastrados, frequência, dias da semana, impacto hídrico, clima para hábitos ao ar livre

Complexidade:
- simple: 1 agente, pergunta direta
- medium: 2 agentes, análise cruzada
- complex: 3 agentes ou cruzamento profundo

Retorne JSON exatamente neste formato (sem markdown, sem texto antes ou depois):
{"intent": "<string>", "complexity": "<simple|medium|complex>", "agents": ["<nome>", ...]}

Exemplos:
- "Quanto vou gastar este mês?" → {"intent": "consumption_forecast", "complexity": "simple", "agents": ["forecast"]}
- "Meus hábitos afetam minha conta?" → {"intent": "habits_impact", "complexity": "medium", "agents": ["habits", "forecast"]}
- "Tenho vazamento e minha conta está alta?" → {"intent": "leak_and_forecast", "complexity": "medium", "agents": ["leak", "forecast"]}
- "Analise tudo: consumo, hábitos e vazamento." → {"intent": "full_analysis", "complexity": "complex", "agents": ["forecast", "leak", "habits"]}
- "Como vai o Brasil?" → {"intent": "unknown", "complexity": "simple", "agents": []}
"""


class RoutingDecision(BaseModel):
    intent: str
    complexity: Literal["simple", "medium", "complex"]
    agents: list[str]


def classify(question: str, context: dict) -> RoutingDecision:
    from app.services.llms import llm_rapido
    from langchain_core.messages import HumanMessage, SystemMessage

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
            [SystemMessage(content=_ROUTER_PROMPT), HumanMessage(content=user_text)]
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
