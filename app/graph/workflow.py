from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.graph.state import AgentOutput, GraphState
from app.graph.context import build_context
from app.graph.router import AGENT_REGISTRY, RoutingDecision, classify, load_agent


def _context_node(state: GraphState) -> GraphState:
    ctx = build_context(state["user_id"], state["session_id"], state["question"])
    return {
        **state,
        "recent_messages": ctx["recent_messages"],
        "relevant_memory": ctx["relevant_memory"],
    }


def _route_node(state: GraphState) -> GraphState:
    ctx = {
        "recent_messages": state.get("recent_messages", []),
        "relevant_memory": state.get("relevant_memory", []),
    }
    decision = classify(state["question"], ctx)
    return {
        **state,
        "intent": decision.intent,
        "complexity": decision.complexity,
        "selected_agents": decision.agents,
        "agent_used": ", ".join(decision.agents) if decision.agents else "unknown",
    }


def _execute_node(state: GraphState) -> GraphState:
    selected = state.get("selected_agents", [])
    user_id = state["user_id"]
    question = state["question"]

    results: list[dict] = []
    warnings: list[str] = list(state.get("warnings", []))

    for name in selected:
        if name not in AGENT_REGISTRY:
            warnings.append(f"Agente desconhecido ignorado: {name}")
            continue
        try:
            agent = load_agent(name, user_id)
            internal = agent.run(question)
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
                warnings=[str(exc)],
            )
            warnings.append(f"Erro no agente {name}: {exc}")
        results.append(output.model_dump())

    return {**state, "agent_results": results, "warnings": warnings}


def _respond_node(state: GraphState) -> GraphState:
    results = state.get("agent_results", [])
    selected = state.get("selected_agents", [])

    if not selected:
        return {
            **state,
            "response": (
                "Não entendi o que você gostaria de saber. Posso ajudar com "
                "previsão de consumo, detecção de vazamentos ou seus hábitos de água."
            ),
            "chart_data": None,
        }

    successes = [r for r in results if r.get("status") == "success" and r.get("answer")]

    if not successes:
        return {
            **state,
            "response": "Não foi possível obter uma resposta neste momento. Tente novamente.",
            "chart_data": None,
        }

    if len(successes) == 1:
        r = successes[0]
        return {**state, "response": r["answer"], "chart_data": r.get("chart_data")}

    parts = [r["answer"] for r in successes]
    chart_data = next((r["chart_data"] for r in successes if r.get("chart_data")), None)
    return {
        **state,
        "response": "\n\n---\n\n".join(parts),
        "chart_data": chart_data,
    }


_graph = StateGraph(GraphState)

_graph.add_node("context", _context_node)
_graph.add_node("route", _route_node)
_graph.add_node("execute", _execute_node)
_graph.add_node("respond", _respond_node)

_graph.set_entry_point("context")
_graph.add_edge("context", "route")
_graph.add_edge("route", "execute")
_graph.add_edge("execute", "respond")
_graph.add_edge("respond", END)

_memory = MemorySaver()
workflow = _graph.compile(checkpointer=_memory)


def run_workflow(user_id: int, session_id: str, question: str) -> GraphState:
    initial: GraphState = {
        "user_id": user_id,
        "session_id": session_id,
        "question": question,
        "response": "",
        "agent_used": "",
        "chart_data": None,
        "agent_results": [],
        "warnings": [],
        "recent_messages": [],
        "relevant_memory": [],
        "intent": "",
        "complexity": "",
        "selected_agents": [],
    }
    return workflow.invoke(
        initial,
        config={"configurable": {"thread_id": session_id}},
    )
