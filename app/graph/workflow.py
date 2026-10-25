"""Workflow dos agentes Delta, compartilhado pelo chat e pelo console de testes."""
from __future__ import annotations

from dataclasses import asdict
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.graph.state import AgentOutput, GraphState
from app.graph.context import build_context
from app.graph.router import AGENT_REGISTRY, AgentNotImplemented, classify, load_agent
from app.observability.diagnostics import component, current_trace, safe_error


def _context_node(state: GraphState) -> GraphState:
    with component("context"):
        ctx = build_context(state["user_id"], state["session_id"], state["question"])
    return {**state, **ctx}


def _route_node(state: GraphState) -> GraphState:
    with component("router"):
        decision = classify(state["question"], {
            "recent_messages": state.get("recent_messages", []),
            "relevant_memory": state.get("relevant_memory", []),
        })
    if trace := current_trace():
        trace.routing = decision.model_dump()
        trace.selected_agents = list(decision.agents)
    return {
        **state, "intent": decision.intent, "complexity": decision.complexity,
        "selected_agents": decision.agents,
        "agent_used": ", ".join(decision.agents) if decision.agents else "unknown",
    }


def execute_agent(name: str, user_id: int, question: str) -> dict:
    """Executa o mesmo especialista usado pelas abas individuais e pelo grafo."""
    trace = current_trace()
    try:
        with component(name):
            agent = load_agent(name, user_id)
            if trace:
                trace.executed_agents.append(name)
            result = agent.run(question)
            output = AgentOutput(
                agent=name, status="success", answer=result.response,
                sources=result.sources, chart_data=result.chart_data,
                tool_calls=[asdict(call) for call in result.tool_calls],
            )
    except AgentNotImplemented:
        if trace:
            # Um arquivo reservado não é um erro de provedor ou banco.
            trace.errors[:] = [e for e in trace.errors
                               if not (e["stage"] == name and e["code"] == "AgentNotImplemented")]
            for stage in reversed(trace.stages):
                if stage["stage"] == name:
                    stage["status"] = "skipped"
                    break
            trace.skipped_agents.append(name)
            trace.warnings.append(f"Agente {name} pendente; etapa ignorada.")
        output = AgentOutput(agent=name, status="skipped", answer="",
                             warnings=[f"Agente {name} ainda não implementado."])
    except Exception as error:
        output = AgentOutput(agent=name, status="error", answer="", warnings=[safe_error(error)])
    return output.model_dump()


def _execute_node(state: GraphState) -> GraphState:
    results = []
    warnings = list(state.get("warnings", []))
    for name in state.get("selected_agents", []):
        if name not in AGENT_REGISTRY:
            warnings.append(f"Agente desconhecido ignorado: {name}")
            if trace := current_trace():
                trace.skipped_agents.append(name)
            continue
        result = execute_agent(name, state["user_id"], state["question"])
        results.append(result)
        warnings.extend(result["warnings"])
    return {**state, "agent_results": results, "warnings": warnings}


def _respond_node(state: GraphState) -> GraphState:
    with component("response"):
        if not state.get("selected_agents"):
            return {**state, "response": (
                "Não entendi o que você gostaria de saber. Posso ajudar com "
                "consumo registrado, previsão, indícios de vazamentos, hábitos ou dúvidas sobre o Delta."
            ), "chart_data": None}
        successes = [r for r in state.get("agent_results", [])
                     if r.get("status") == "success" and r.get("answer")]
        if not successes:
            return {**state, "response": "Não foi possível obter uma resposta neste momento. Tente novamente.",
                    "chart_data": None}
        chart = next((r["chart_data"] for r in successes if r.get("chart_data")), None)
        return {**state, "response": "\n\n---\n\n".join(r["answer"] for r in successes),
                "chart_data": chart}


_graph = StateGraph(GraphState)
for name, node in (("context", _context_node), ("route", _route_node),
                   ("execute", _execute_node), ("respond", _respond_node)):
    _graph.add_node(name, node)
_graph.set_entry_point("context")
_graph.add_edge("context", "route")
_graph.add_edge("route", "execute")
_graph.add_edge("execute", "respond")
_graph.add_edge("respond", END)
workflow = _graph.compile(checkpointer=MemorySaver())


def run_workflow(user_id: int, session_id: str, question: str) -> GraphState:
    initial: GraphState = {
        "user_id": user_id, "session_id": session_id, "question": question,
        "response": "", "agent_used": "", "chart_data": None, "agent_results": [],
        "warnings": [], "recent_messages": [], "relevant_memory": [],
        "intent": "", "complexity": "", "selected_agents": [],
    }
    return workflow.invoke(initial, config={"configurable": {"thread_id": f"{user_id}:{session_id}"}})
