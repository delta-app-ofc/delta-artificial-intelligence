"""Workflow dos agentes Delta, compartilhado pelo chat e pelo console de testes."""
from __future__ import annotations

from dataclasses import asdict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.graph.context import build_context
from app.graph.router import AGENT_REGISTRY, AgentNotImplemented, classify, load_agent
from app.graph.state import AgentOutput, GraphState
from app.graph.synthesis import synthesize
from app.guardrails.input import validate_input
from app.guardrails.output import validate_output
from app.memory.session import append_turn, load_history_validated
from app.observability.diagnostics import component, current_trace, safe_error

RECENT_TURNS = 6


def _recent_messages(state: GraphState) -> list[dict]:
    previous = state.get("messages", [])[:-1]
    return [{"role": message.type, "content": message.content}
            for message in previous[-RECENT_TURNS:]]


def _guardrail_input_node(state: GraphState) -> dict:
    with component("input_guard"):
        result = validate_input(state["user_id"], state["question"])
    if not result["ok"]:
        if trace := current_trace():
            trace.errors.append({"stage": "input_guard", "code": "input_rejected",
                                 "message": result.get("reason", "Mensagem bloqueada.")})
        return {"response": result.get("reason", "Mensagem bloqueada."),
                "pii_map": {}, "_blocked": True}
    return {"question": result["message"],
            "messages": [{"role": "human", "content": result["message"]}],
            "pii_map": result.get("pii_map") or {}, "_blocked": False}


def _after_guardrail_input(state: GraphState) -> str:
    return END if state.get("_blocked") else "context"


def _context_node(state: GraphState) -> dict:
    with component("context"):
        return build_context(state["user_id"], state["session_id"], state["question"])


def _route_node(state: GraphState) -> dict:
    context = {
        "recent_messages": state.get("recent_messages") or _recent_messages(state),
        "relevant_memory": state.get("relevant_memory", []),
    }
    with component("router"):
        decision = classify(state["question"], context)
    if trace := current_trace():
        trace.routing = decision.model_dump()
        trace.selected_agents = list(decision.agents)
    return {"intent": decision.intent, "complexity": decision.complexity,
            "selected_agents": decision.agents,
            "agent_used": ", ".join(decision.agents) if decision.agents else "unknown"}


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
            trace.errors[:] = [
                error for error in trace.errors
                if not (error["stage"] == name and error["code"] == "AgentNotImplemented")
            ]
            for stage in reversed(trace.stages):
                if stage["stage"] == name:
                    stage["status"] = "skipped"
                    break
            trace.skipped_agents.append(name)
            trace.warnings.append(f"Agente {name} pendente; etapa ignorada.")
        output = AgentOutput(agent=name, status="skipped", answer="",
                             warnings=[f"Agente {name} ainda não implementado."])
    except Exception as error:
        output = AgentOutput(agent=name, status="error", answer="",
                             warnings=[safe_error(error)])
    return output.model_dump()


def _execute_node(state: GraphState) -> dict:
    question = state["question"]
    history = _recent_messages(state)
    if history:
        transcript = "\n".join(f"{message['role']}: {message['content']}" for message in history)
        question += f"\n\nConversa recente:\n{transcript}"

    results: list[dict] = []
    warnings: list[str] = list(state.get("warnings", []))
    for name in state.get("selected_agents", []):
        if name not in AGENT_REGISTRY:
            warnings.append(f"Agente desconhecido ignorado: {name}")
            if trace := current_trace():
                trace.skipped_agents.append(name)
            continue
        prior = "\n".join(
            f"- {result['agent']}: {result['answer'][:300]}"
            for result in results
            if result.get("status") == "success" and result.get("answer")
        )
        agent_question = (
            f"{question}\n\nContexto dos agentes anteriores:\n{prior}" if prior else question
        )
        result = execute_agent(name, state["user_id"], agent_question)
        results.append(result)
        warnings.extend(result.get("warnings", []))
    return {"agent_results": results, "warnings": warnings}


def _synthesize_node(state: GraphState) -> dict:
    results = state.get("agent_results", [])
    successes = [result for result in results
                 if result.get("status") == "success" and result.get("answer")]
    if len(successes) < 2:
        return {}
    with component("synthesis"):
        return synthesize(state["question"], successes) or {}


def _respond_node(state: GraphState) -> dict:
    with component("response"):
        if state.get("intent") == "privacy_violation":
            return {"response": ("Não tenho acesso a dados de outros usuários. "
                                 "Posso ajudar apenas com informações da sua conta."),
                    "chart_data": None}
        if state.get("response"):
            return {}
        results = state.get("agent_results", [])
        selected = state.get("selected_agents", [])
        if not selected:
            return {"response": ("Não entendi o que você gostaria de saber. Posso ajudar com "
                                 "previsão de consumo, detecção de vazamentos ou seus hábitos de água."),
                    "chart_data": None}
        successes = [result for result in results
                     if result.get("status") == "success" and result.get("answer")]
        if not successes:
            return {"response": "Não foi possível obter uma resposta neste momento.",
                    "chart_data": None}
        if len(successes) == 1:
            result = successes[0]
            return {"response": result["answer"], "chart_data": result.get("chart_data")}
        chart = next((result["chart_data"] for result in successes
                      if result.get("chart_data")), None)
        return {"response": "\n\n---\n\n".join(result["answer"] for result in successes),
                "chart_data": chart}


def _guardrail_output_node(state: GraphState) -> dict:
    if state.get("_blocked"):
        return {}
    with component("output_guard"):
        result = validate_output(state.get("response") or "", state.get("pii_map") or {})
    if not result["ok"]:
        if trace := current_trace():
            trace.errors.append({"stage": "output_guard", "code": "output_rejected",
                                 "message": result.get("reason", "Resposta bloqueada.")})
        safe = "Não foi possível processar a resposta."
    else:
        safe = result["response"]

    if state.get("_persist_session", True):
        try:
            with component("session_save"):
                append_turn(state["session_id"], state["user_id"], "human", state["question"])
                append_turn(state["session_id"], state["user_id"], "assistant", safe)
        except Exception:
            # component() registra o erro sem descartar a resposta ao usuário.
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
    "guardrail_input", _after_guardrail_input,
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
    try:
        history = load_history_validated(user_id, session_id)
    except Exception as error:
        if trace := current_trace():
            trace.error("session_history", error)
        return []
    return [{"role": item["role"], "content": item["content"]}
            for item in history[-RECENT_TURNS:]
            if item.get("role") in ("human", "assistant")]


def run_workflow(user_id: int, session_id: str, question: str, *,
                 persist_session: bool = True) -> GraphState:
    config = {"configurable": {"thread_id": f"{user_id}:{session_id}"}}
    initial: GraphState = {
        "user_id": user_id, "session_id": session_id, "question": question,
        "response": "", "agent_used": "", "chart_data": None,
        "agent_results": [], "warnings": [], "recent_messages": [],
        "relevant_memory": [], "intent": "", "complexity": "", "selected_agents": [],
        "_persist_session": persist_session,
    }
    if not workflow.get_state(config).values.get("messages"):
        initial["messages"] = _history_from_mongo(user_id, session_id)
    return workflow.invoke(initial, config=config)