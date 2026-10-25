from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.graph.context import find_relevant_memory
from app.graph.router import AGENT_REGISTRY, classify, load_agent
from app.graph.state import AgentOutput, GraphState

RECENT_TURNS = 6

_SYNTHESIS_PROMPT = """\
Você é o assistente Delta. Recebeu respostas de {n} especialistas para a mesma pergunta.
Unifique-as em uma resposta clara e direta, sem repetições, preservando a origem de cada
dado (qual agente forneceu o quê), as limitações declaradas e as incertezas. Não invente
dados. Se houver contradição entre especialistas, sinalize explicitamente.

Pergunta: {question}

{respostas}
"""


def _recent_messages(state: GraphState) -> list[dict]:
    """Últimas mensagens da conversa, sem a pergunta atual (a última da lista)."""
    previous = state.get("messages", [])[:-1]
    return [{"role": m.type, "content": m.content} for m in previous[-RECENT_TURNS:]]


def _guardrail_input_node(state: GraphState) -> dict:
    """Valida a entrada antes de qualquer processamento (defesa em profundidade)."""
    from app.guardrails.input import validate_input

    result = validate_input(state["user_id"], state["question"])
    if not result["ok"]:
        return {
            "response": result.get("reason", "Mensagem bloqueada."),
            "pii_map": {},
            "_blocked": True,
        }
    return {
        "question": result["message"],
        "messages": [{"role": "human", "content": result["message"]}],
        "pii_map": result.get("pii_map") or {},
        "_blocked": False,
    }


def _after_guardrail_input(state: GraphState) -> str:
    return END if state.get("_blocked") else "context"


def _context_node(state: GraphState) -> dict:
    return {"relevant_memory": find_relevant_memory(state["user_id"], state["question"])}


def _route_node(state: GraphState) -> dict:
    ctx = {
        "recent_messages": _recent_messages(state),
        "relevant_memory": state.get("relevant_memory", []),
    }
    decision = classify(state["question"], ctx)
    return {
        "intent": decision.intent,
        "complexity": decision.complexity,
        "selected_agents": decision.agents,
        "agent_used": ", ".join(decision.agents) if decision.agents else "unknown",
    }


def _execute_node(state: GraphState) -> dict:
    selected = state.get("selected_agents", [])
    user_id = state["user_id"]

    question = state["question"]
    history = "\n".join(f"{m['role']}: {m['content']}" for m in _recent_messages(state))
    if history:
        question += f"\n\nConversa recente:\n{history}"

    results: list[dict] = []
    warnings: list[str] = list(state.get("warnings", []))

    for name in selected:
        if name not in AGENT_REGISTRY:
            warnings.append(f"Agente desconhecido ignorado: {name}")
            continue
        try:
            agent = load_agent(name, user_id)
            prior = "\n".join(
                f"- {r['agent']}: {r['answer'][:300]}"
                for r in results
                if r.get("status") == "success" and r.get("answer")
            )
            agent_question = (
                f"{question}\n\nContexto dos agentes anteriores:\n{prior}" if prior else question
            )
            internal = agent.run(agent_question)
            output = AgentOutput(
                agent=name,
                status="success",
                answer=internal.response,
                chart_data=internal.chart_data,
            )
        except Exception as exc:
            output = AgentOutput(
                agent=name,
                status="error",
                answer="",
                warnings=[type(exc).__name__],
            )
            warnings.append(f"Erro no agente {name}: {type(exc).__name__}")
        results.append(output.model_dump())

    return {"agent_results": results, "warnings": warnings}


def _synthesize_node(state: GraphState) -> dict:
    """Une respostas de múltiplos agentes num texto coeso via LLM rápido."""
    results = state.get("agent_results", [])
    successes = [r for r in results if r.get("status") == "success" and r.get("answer")]

    if len(successes) < 2:
        return {}

    import app.services.llms as _llm_module
    from langchain_core.messages import HumanMessage, SystemMessage

    llm_rapido = _llm_module.llm_rapido
    if llm_rapido is None:
        return {}

    respostas_texto = "\n\n".join(
        f"[{r['agent'].upper()}]\n{r['answer']}" for r in successes
    )
    prompt = _SYNTHESIS_PROMPT.format(
        n=len(successes),
        question=state["question"],
        respostas=respostas_texto,
    )

    try:
        response = llm_rapido.invoke(
            [SystemMessage(content=prompt), HumanMessage(content="Unifique as respostas.")]
        )
        unified = response.content if hasattr(response, "content") else str(response)
        if unified.strip():
            chart_data = next(
                (r["chart_data"] for r in successes if r.get("chart_data")), None
            )
            return {"response": unified.strip(), "chart_data": chart_data}
    except Exception:
        pass

    return {}


def _respond_node(state: GraphState) -> dict:
    if state.get("intent") == "privacy_violation":
        return {
            "response": (
                "Não tenho acesso a dados de outros usuários. "
                "Posso ajudar apenas com informações da sua conta."
            ),
            "chart_data": None,
        }

    if state.get("response"):
        return {}

    results = state.get("agent_results", [])
    selected = state.get("selected_agents", [])

    if not selected:
        return {
            "response": (
                "Não entendi o que você gostaria de saber. Posso ajudar com "
                "previsão de consumo, detecção de vazamentos ou seus hábitos de água."
            ),
            "chart_data": None,
        }

    successes = [r for r in results if r.get("status") == "success" and r.get("answer")]

    if not successes:
        return {
            "response": "Não foi possível obter uma resposta neste momento. Tente novamente.",
            "chart_data": None,
        }

    if len(successes) == 1:
        r = successes[0]
        return {"response": r["answer"], "chart_data": r.get("chart_data")}

    parts = [r["answer"] for r in successes]
    chart_data = next((r["chart_data"] for r in successes if r.get("chart_data")), None)
    return {"response": "\n\n---\n\n".join(parts), "chart_data": chart_data}


def _guardrail_output_node(state: GraphState) -> dict:
    """Sanitiza a resposta e grava a conversa no Mongo ao final."""
    from app.guardrails.output import validate_output
    from app.memory.session import append_turn

    response = state.get("response") or ""
    result = validate_output(response, state.get("pii_map") or {})
    safe = result["response"] if result.get("ok") else "Não foi possível processar a resposta."

    try:
        append_turn(state["session_id"], state["user_id"], "human", state["question"])
        append_turn(state["session_id"], state["user_id"], "assistant", safe)
    except Exception:
        pass

    return {"response": safe, "messages": [{"role": "assistant", "content": safe}]}


_graph = StateGraph(GraphState)

_graph.add_node("guardrail_input", _guardrail_input_node)
_graph.add_node("context", _context_node)
_graph.add_node("route", _route_node)
_graph.add_node("execute", _execute_node)
_graph.add_node("synthesize", _synthesize_node)
_graph.add_node("respond", _respond_node)
_graph.add_node("guardrail_output", _guardrail_output_node)

_graph.set_entry_point("guardrail_input")
_graph.add_conditional_edges(
    "guardrail_input",
    _after_guardrail_input,
    {END: END, "context": "context"},
)
_graph.add_edge("context", "route")
_graph.add_edge("route", "execute")
_graph.add_edge("execute", "synthesize")
_graph.add_edge("synthesize", "respond")
_graph.add_edge("respond", "guardrail_output")
_graph.add_edge("guardrail_output", END)

workflow = _graph.compile(checkpointer=MemorySaver())


def _history_from_mongo(user_id: int, session_id: str) -> list[dict]:
    """Recupera a conversa gravada, para retomar após reinício do servidor."""
    from app.memory.session import load_history_validated

    try:
        history = load_history_validated(user_id, session_id)
    except Exception:
        return []
    return [
        {"role": m["role"], "content": m["content"]}
        for m in history[-RECENT_TURNS:]
        if m.get("role") in ("human", "assistant")
    ]


def run_workflow(user_id: int, session_id: str, question: str) -> GraphState:
    config = {"configurable": {"thread_id": f"{user_id}:{session_id}"}}

    # Todo campo, exceto `messages`, é reiniciado a cada pergunta.
    initial: GraphState = {
        "user_id": user_id,
        "session_id": session_id,
        "question": question,
        "response": "",
        "agent_used": "",
        "chart_data": None,
        "agent_results": [],
        "warnings": [],
        "relevant_memory": [],
        "intent": "",
        "complexity": "",
        "selected_agents": [],
    }
    if not workflow.get_state(config).values.get("messages"):
        initial["messages"] = _history_from_mongo(user_id, session_id)

    return workflow.invoke(initial, config=config)
