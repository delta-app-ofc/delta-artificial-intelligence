"""Workflow dos agentes Delta, compartilhado pelo chat e pelo console de testes."""
from __future__ import annotations

import json
from dataclasses import asdict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.agents.judge import JudgeAgent, JudgeInput, SAFE_RESPONSE
from app.graph.context import build_context
from app.graph.router import AGENT_REGISTRY, AgentNotImplemented, classify, load_agent
from app.graph.state import AgentOutput, GraphState
from app.graph.synthesis import synthesize
from app.guardrails.input import validate_input
from app.guardrails.output import validate_output
from app.memory.session import append_turn, load_history_validated
from app.observability.diagnostics import component, current_trace, safe_error

RECENT_TURNS = 6
_GREETING_RESPONSE = (
    "Oi! Posso ajudar com seu consumo de água, previsões, alertas e hábitos. "
    "O que você gostaria de saber?"
)
_NO_AGENT_RESPONSE = (
    "Não entendi o que você gostaria de saber. Posso ajudar com previsão de consumo, "
    "detecção de vazamentos ou seus hábitos de água."
)
_AGENT_FAILURE_RESPONSE = "Não foi possível obter uma resposta neste momento. Tente novamente."
_REVISION_FALLBACK = (
    "Revise a candidata conforme os critérios pendentes e use somente as evidências disponíveis."
)


def _recent_messages(state: GraphState) -> list[dict]:
    previous = state.get("messages", [])[:-1]
    return [
        {"role": message.type, "content": message.content}
        for message in previous[-RECENT_TURNS:]
    ]


def _redact_judge_context_text(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    from app.guardrails.input import anonymize

    anonymized, pii_map = anonymize(value)
    checked = validate_output(anonymized, pii_map=pii_map)
    return checked["response"] if checked.get("ok") else None


def _safe_recent_messages(messages: object) -> list[dict[str, str]]:
    if not isinstance(messages, list):
        return []
    safe_messages = []
    for message in messages:
        if not isinstance(message, dict) or not isinstance(message.get("role"), str):
            continue
        content = _redact_judge_context_text(message.get("content"))
        if content is not None:
            safe_messages.append({"role": message["role"], "content": content})
    return safe_messages


def _safe_relevant_memory(items: object) -> list[str]:
    if not isinstance(items, list):
        return []
    return [content for item in items if (content := _redact_judge_context_text(item))]


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


def _previous_result(state: GraphState, agent_name: str) -> dict:
    return next(
        (result for result in state.get("previous_agent_results", [])
         if result.get("agent") == agent_name),
        {},
    )


def _serialize_tool_calls(calls: list, stage: str) -> list[dict]:
    serialized = []
    for call in calls:
        item = dict(call) if isinstance(call, dict) else asdict(call)
        item.setdefault("stage", stage)
        serialized.append(item)
    return serialized


def execute_agent(
    name: str,
    user_id: int,
    question: str,
    *,
    revision_feedback: str | None = None,
    revision_context: dict | None = None,
) -> dict:
    """Executa o mesmo especialista usado pelas abas individuais e pelo grafo."""
    trace = current_trace()
    try:
        with component(name):
            agent = load_agent(name, user_id)
            if trace:
                trace.executed_agents.append(name)
            if revision_feedback or revision_context:
                result = agent.run(
                    question,
                    revision_feedback=revision_feedback,
                    revision_context=revision_context,
                )
            else:
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

    results = []
    warnings = list(state.get("warnings", []))
    revision_count = state.get("revision_count", 0)
    for name in state.get("selected_agents", []):
        if name not in AGENT_REGISTRY:
            warnings.append(f"Agente desconhecido ignorado: {name}")
            if trace := current_trace():
                trace.skipped_agents.append(name)
            continue

        prior_result = _previous_result(state, name) if revision_count else {}
        prior_answers = "\n".join(
            f"- {result['agent']}: {result['answer'][:300]}"
            for result in results
            if result.get("status") == "success" and result.get("answer")
        )
        agent_question = (
            f"{question}\n\nContexto dos agentes anteriores:\n{prior_answers}"
            if prior_answers else question
        )
        output = execute_agent(
            name,
            state["user_id"],
            agent_question,
            revision_feedback=state.get("revision_feedback") if revision_count else None,
            revision_context={
                "candidate": state.get("previous_candidate") or "",
                "agent_result": prior_result,
            } if revision_count else None,
        )
        previous_calls = _serialize_tool_calls(prior_result.get("tool_calls", []), "previous")
        current_calls = _serialize_tool_calls(
            output.get("tool_calls", []), "revision" if revision_count else "initial"
        )
        output["tool_calls"] = previous_calls + current_calls
        output["sources"] = list(dict.fromkeys(
            prior_result.get("sources", []) + output.get("sources", [])
        ))
        if output.get("chart_data") is None:
            output["chart_data"] = prior_result.get("chart_data")
        results.append(output)
        warnings.extend(output.get("warnings", []))
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
            response = _GREETING_RESPONSE if state.get("intent") == "greeting" else _NO_AGENT_RESPONSE
            return {"response": response, "chart_data": None}
        successes = [result for result in results
                     if result.get("status") == "success" and result.get("answer")]
        if not successes:
            return {"response": _AGENT_FAILURE_RESPONSE, "chart_data": None}
        chart = next((result["chart_data"] for result in successes
                      if result.get("chart_data")), None)
        if len(successes) == 1:
            return {"response": successes[0]["answer"], "chart_data": chart}
        return {"response": "\n\n---\n\n".join(result["answer"] for result in successes),
                "chart_data": chart}


def _compose_node(state: GraphState) -> dict:
    if state.get("intent") == "privacy_violation":
        return {"composition_status": "bypass", "candidate": ""}
    if not state.get("selected_agents"):
        return {"composition_status": "no_agents", "candidate": ""}
    successes = [result for result in state.get("agent_results", [])
                 if result.get("status") == "success" and result.get("answer", "").strip()]
    if not successes:
        return {"composition_status": "no_success", "candidate": ""}
    return {"composition_status": "ready", "candidate": state.get("response", "")}


def _judge_node(state: GraphState) -> dict:
    candidate = state.get("candidate", "")
    revision_count = state.get("revision_count", 0)
    agent_results = state.get("agent_results", [])
    context = {
        "selected_agents": state.get("selected_agents", []),
        "agent_errors": [result.get("agent") for result in agent_results
                         if result.get("status") != "success"],
        "recent_messages": _safe_recent_messages(state.get("recent_messages", [])[-4:]),
        "relevant_memory": _safe_relevant_memory(state.get("relevant_memory", [])[:2]),
        "warnings": state.get("warnings", []),
        "revision_count": revision_count,
        "previous_candidate": state.get("previous_candidate"),
        "previous_agent_results": state.get("previous_agent_results", []),
    }
    try:
        with component("judge"):
            result = JudgeAgent().run(
                JudgeInput(
                    question=state["question"],
                    candidate=candidate,
                    agent_results=agent_results,
                    context=context,
                    chart_data=state.get("chart_data"),
                ),
                revision_count=revision_count,
            )
        judge_output = result.model_dump()
        decision, status = result.decision, result.status
    except Exception as error:
        if trace := current_trace():
            trace.error("judge", error)
        judge_output = {
            "decision": "reject", "status": "unavailable",
            "justification": "A avaliação automática não está disponível neste momento.",
            "reason_codes": ["JUDGE_UNAVAILABLE"], "confidence": None,
            "severity": None, "assessment": {},
        }
        decision, status = "reject", "unavailable"

    history = list(state.get("judge_history", []))
    history.append({"candidate": candidate, "judge": judge_output,
                    "agent_results": agent_results, "chart_data": state.get("chart_data")})
    if status == "evaluated" and decision == "approve":
        action = "approve"
    elif status == "evaluated" and decision == "correct" and revision_count == 0:
        action = "correct"
    else:
        action = "block"
    return {"judge_history": history, "judge_action": action}


def _prepare_revision_node(state: GraphState) -> dict:
    last_judge = state.get("judge_history", [])[-1].get("judge", {})
    feedback = (last_judge.get("justification") or "").strip() or _REVISION_FALLBACK
    return {
        "previous_candidate": state.get("candidate", ""),
        "previous_agent_results": state.get("agent_results", []),
        "revision_feedback": feedback,
        "revision_count": state.get("revision_count", 0) + 1,
        "candidate": "", "agent_results": [], "response": "", "chart_data": None,
        "composition_status": "", "judge_action": "", "warnings": [],
    }


def _publish_node(state: GraphState) -> dict:
    return {"response": state.get("candidate", ""),
            "chart_data": state.get("chart_data")}


def _block_node(state: GraphState) -> dict:
    return {"response": SAFE_RESPONSE, "chart_data": None}


def _after_compose(state: GraphState) -> str:
    return "judge" if state.get("composition_status") == "ready" else "output_guard"


def _after_judge(state: GraphState) -> str:
    action = state.get("judge_action")
    if action == "approve":
        return "publish"
    if action == "correct" and state.get("revision_count", 0) == 0:
        return "revise"
    return "block"


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
            pass
    return {"response": safe, "messages": [{"role": "assistant", "content": safe}]}


_graph = StateGraph(GraphState)
_graph.add_node("guardrail_input", _guardrail_input_node)
_graph.add_node("context", _context_node)
_graph.add_node("route", _route_node)
_graph.add_node("execute", _execute_node)
_graph.add_node("synthesize", _synthesize_node)
_graph.add_node("respond", _respond_node)
_graph.add_node("compose", _compose_node)
_graph.add_node("judge", _judge_node)
_graph.add_node("revise", _prepare_revision_node)
_graph.add_node("publish", _publish_node)
_graph.add_node("block", _block_node)
_graph.add_node("output_guard", _guardrail_output_node)
_graph.set_entry_point("guardrail_input")
_graph.add_conditional_edges("guardrail_input", _after_guardrail_input,
                             {END: END, "context": "context"})
_graph.add_edge("context", "route")
_graph.add_edge("route", "execute")
_graph.add_edge("execute", "synthesize")
_graph.add_edge("synthesize", "respond")
_graph.add_edge("respond", "compose")
_graph.add_conditional_edges("compose", _after_compose,
                             {"judge": "judge", "output_guard": "output_guard"})
_graph.add_conditional_edges("judge", _after_judge,
                             {"publish": "publish", "revise": "revise", "block": "block"})
_graph.add_edge("revise", "execute")
_graph.add_edge("publish", "output_guard")
_graph.add_edge("block", "output_guard")
_graph.add_edge("output_guard", END)
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
        "candidate": "", "previous_candidate": None, "previous_agent_results": [],
        "revision_feedback": "", "revision_count": 0, "judge_history": [],
        "judge_action": "", "composition_status": "", "pii_map": {}, "_blocked": False,
    }
    if not workflow.get_state(config).values.get("messages"):
        initial["messages"] = _history_from_mongo(user_id, session_id)
    return workflow.invoke(initial, config=config)
