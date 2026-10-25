from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel
from app.config import ConfigurationError
from app.observability.diagnostics import current_trace

AGENT_REGISTRY: dict[str, str] = {
    "consumption": "app.agents.consumption.ConsumptionAgent",
    "forecast": "app.agents.forecast.ForecastAgent",
    "leak": "app.agents.leak.LeakAgent",
    "habits": "app.agents.habits.HabitsAgent",
    "rag": "app.agents.rag.RagAgent",
}

_ROUTER_PROMPT = """Você é o roteador do Delta AI, assistente de monitoramento de consumo de água.
Classifique a pergunta e decida quais agentes devem responder.

Agentes disponíveis:
- consumption: consumo registrado, totais, médias, comparação de períodos e picos diários; não prevê conta futura
- forecast: previsão de consumo, estimativa da próxima conta, tendência, risco de meta
- leak: possíveis vazamentos, consumo anormal, alertas de comportamento atípico
- habits: hábitos cadastrados, frequência, dias da semana, impacto hídrico, clima para hábitos ao ar livre
- rag: explicações da documentação oficial do Delta, cadastro, vínculo do hidrômetro,
  significado de indicadores, regras de metas, alertas, privacidade e funcionalidades

Use rag para explicar como o produto funciona. Consultas sobre dados particulares
da conta devem ir aos especialistas; combine rag e especialista quando a pergunta
pedir tanto uma explicação geral quanto uma análise dos registros do usuário.

Complexidade:
- simple: 1 agente, pergunta direta
- medium: 2 agentes, análise cruzada
- complex: 3 ou mais agentes ou cruzamento profundo

Retorne JSON exatamente neste formato (sem markdown, sem texto antes ou depois):
{"intent": "<string>", "complexity": "<simple|medium|complex>", "agents": ["<nome>", ...]}

Exemplos:
- "Quanto vou gastar este mês?" → {"intent": "consumption_forecast", "complexity": "simple", "agents": ["forecast"]}
- "Meus hábitos afetam minha conta?" → {"intent": "habits_impact", "complexity": "medium", "agents": ["habits", "forecast"]}
- "Tenho vazamento e minha conta está alta?" → {"intent": "leak_and_forecast", "complexity": "medium", "agents": ["leak", "forecast"]}
- "Analise tudo: consumo, hábitos e vazamento." → {"intent": "full_analysis", "complexity": "complex", "agents": ["forecast", "leak", "habits"]}
- "Como vai o Brasil?" → {"intent": "unknown", "complexity": "simple", "agents": []}
- "Como vinculo meu hidrômetro?" → {"intent": "product_help", "complexity": "simple", "agents": ["rag"]}
- "O que é um indício de vazamento?" → {"intent": "product_help", "complexity": "simple", "agents": ["rag"]}
- "O que é um alerta e tenho algum ativo?" → {"intent": "alert_help", "complexity": "medium", "agents": ["rag", "leak"]}
"""


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
        if llm_rapido is None:
            raise ConfigurationError("Configure GROQ_API_KEY e GROQ_FAST_MODEL para o roteador.")
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
        if trace := current_trace():
            trace.skipped_agents.extend(a for a in decision.agents if a not in known)
        decision.agents = list(dict.fromkeys(a for a in decision.agents if a in known))
        return decision
    except Exception as error:
        if trace := current_trace():
            trace.error("router", error)

    return RoutingDecision(intent="unknown", complexity="simple", agents=[])


def load_agent(name: str, user_id: int):
    """Instancia o agente pelo nome, consultando AGENT_REGISTRY."""
    import importlib

    module_path, class_name = AGENT_REGISTRY[name].rsplit(".", 1)
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name, None)
    if cls is None or not callable(getattr(cls, "run", None)):
        raise AgentNotImplemented(name)
    return cls(user_id=user_id)


class AgentNotImplemented(RuntimeError):
    """Componente reservado: não representa uma falha de um agente implementado."""
