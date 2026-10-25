from __future__ import annotations

import json

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.agents.judge import JudgeAgent, JudgeInput, SAFE_RESPONSE
from app.graph.context import build_context
from app.graph.router import AGENT_REGISTRY, classify, load_agent
from app.graph.state import AgentOutput, GraphState

_NO_AGENT_RESPONSE = (
    "Não entendi o que você gostaria de saber. Posso ajudar com previsão de consumo, "
    "detecção de vazamentos ou seus hábitos de água."
)
_AGENT_FAILURE_RESPONSE = "Não foi possível obter uma resposta neste momento. Tente novamente."
_REVISION_FALLBACK = (
    "Revise a candidata conforme os critérios pendentes e use somente as evidências disponíveis."
)


def _redact_judge_context_text(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None

    from app.guardrails.input import anonymize
    from app.guardrails.output import validate_output

    anonymized, pii_map = anonymize(value)
    checked = validate_output(anonymized, pii_map=pii_map)
    return checked["response"] if checked.get("ok") else None


def _safe_recent_messages(messages: object) -> list[dict[str, str]]:
    if not isinstance(messages, list):
        return []

    safe_messages: list[dict[str, str]] = []
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

    safe_items: list[str] = []
    for item in items:
        content = _redact_judge_context_text(item)
        if content is not None:
            safe_items.append(content)
    return safe_items


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


def _previous_result(state: GraphState, agent_name: str) -> dict:
    for result in state.get("previous_agent_results", []):
        if result.get("agent") == agent_name:
            return result
    return {}

def _serialize_tool_calls(calls: list, stage: str) -> list[dict]:
    serialized: list[dict] = []
    for call in calls:
        if isinstance(call, dict):
            item = dict(call)
            item.setdefault("stage", stage)
        else:
            item = {
                "name": call.name,
                "input": call.input,
                "output": call.output,
                "stage": stage,
            }
        serialized.append(item)
    return serialized


def _safe_chart_data(chart_data: dict | None) -> dict | None:
    if chart_data is None:
        return None
    try:
        from plotly.utils import PlotlyJSONEncoder

        return json.loads(json.dumps(chart_data, cls=PlotlyJSONEncoder))
    except (ImportError, TypeError, ValueError):
        try:
            return json.loads(json.dumps(chart_data))
        except (TypeError, ValueError):
            return None

def _execute_node(state: GraphState) -> GraphState:
    selected = state.get("selected_agents", [])
    user_id = state["user_id"]
    question = state["question"]
    revision_count = state.get("revision_count", 0)

    results: list[dict] = []
    warnings: list[str] = list(state.get("warnings", []))

    for name in selected:
        if name not in AGENT_REGISTRY:
            warnings.append("Agente desconhecido ignorado pelo roteador.")
            continue

        previous = _previous_result(state, name) if revision_count else {}
        try:
            agent = load_agent(name, user_id)
            if revision_count:
                internal = agent.run(
                    question,
                    revision_feedback=state.get("revision_feedback", ""),
                    revision_context={
                        "candidate": state.get("previous_candidate") or "",
                        "agent_result": previous,
                    },
                )
            else:
                internal = agent.run(question)

            tool_calls = _serialize_tool_calls(
                previous.get("tool_calls", []), "previous"
            )
            tool_calls.extend(
                _serialize_tool_calls(
                    internal.tool_calls,
                    "revision" if revision_count else "initial",
                )
            )
            sources = list(
                dict.fromkeys(previous.get("sources", []) + internal.sources)
            )
            output = AgentOutput(
                agent=name,
                status="success",
                answer=internal.response,
                sources=sources,
                chart_data=_safe_chart_data(internal.chart_data or previous.get("chart_data")),
                tool_calls=tool_calls,
            )
        except Exception:
            previous_calls = _serialize_tool_calls(
                previous.get("tool_calls", []), "previous"
            )
            output = AgentOutput(
                agent=name,
                status="error",
                answer="",
                sources=previous.get("sources", []),
                chart_data=_safe_chart_data(previous.get("chart_data")),
                tool_calls=previous_calls,
                warnings=[f"Falha ao executar o agente {name}."],
            )
            warnings.append(f"Falha ao executar o agente {name}.")
        results.append(output.model_dump())

    return {**state, "agent_results": results, "warnings": warnings}


def _compose_node(state: GraphState) -> GraphState:
    selected = state.get("selected_agents", [])
    if not selected:
        return {
            **state,
            "composition_status": "no_agents",
            "candidate": "",
            "response": _NO_AGENT_RESPONSE,
            "chart_data": None,
        }

    successes = [
        result
        for result in state.get("agent_results", [])
        if result.get("status") == "success" and result.get("answer", "").strip()
    ]
    if not successes:
        return {
            **state,
            "composition_status": "no_success",
            "candidate": "",
            "response": _AGENT_FAILURE_RESPONSE,
            "chart_data": None,
        }

    candidate = "\n\n---\n\n".join(result["answer"] for result in successes)
    chart_data = next(
        (result.get("chart_data") for result in successes if result.get("chart_data")),
        None,
    )
    return {
        **state,
        "composition_status": "ready",
        "candidate": candidate,
        "response": "",
        "chart_data": chart_data,
    }


def _judge_node(state: GraphState) -> GraphState:
    candidate = state.get("candidate", "")
    revision_count = state.get("revision_count", 0)
    agent_results = state.get("agent_results", [])
    context = {
        "selected_agents": state.get("selected_agents", []),
        "agent_errors": [
            result.get("agent")
            for result in agent_results
            if result.get("status") != "success"
        ],
        "recent_messages": _safe_recent_messages(
            state.get("recent_messages", [])[-4:]
        ),
        "relevant_memory": _safe_relevant_memory(
            state.get("relevant_memory", [])[:2]
        ),
        "warnings": state.get("warnings", []),
        "revision_count": revision_count,
        "previous_candidate": state.get("previous_candidate"),
        "previous_agent_results": state.get("previous_agent_results", []),
    }

    try:
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
        decision = result.decision
        status = result.status
    except Exception:
        judge_output = {
            "decision": "reject",
            "status": "unavailable",
            "justification": "A avaliação automática não está disponível neste momento.",
            "reason_codes": ["JUDGE_UNAVAILABLE"],
            "confidence": None,
            "severity": None,
            "assessment": {},
        }
        decision = "reject"
        status = "unavailable"

    history = list(state.get("judge_history", []))
    history.append(
        {
            "candidate": candidate,
            "judge": judge_output,
            "agent_results": agent_results,
            "chart_data": state.get("chart_data"),
        }
    )

    if status == "evaluated" and decision == "approve":
        action = "approve"
    elif status == "evaluated" and decision == "correct" and revision_count == 0:
        action = "correct"
    else:
        action = "block"

    return {**state, "judge_history": history, "judge_action": action}


def _prepare_revision_node(state: GraphState) -> GraphState:
    last_judge = state.get("judge_history", [])[-1].get("judge", {})
    feedback = (last_judge.get("justification") or "").strip() or _REVISION_FALLBACK
    return {
        **state,
        "previous_candidate": state.get("candidate", ""),
        "previous_agent_results": state.get("agent_results", []),
        "revision_feedback": feedback,
        "revision_count": state.get("revision_count", 0) + 1,
        "candidate": "",
        "agent_results": [],
        "response": "",
        "chart_data": None,
        "composition_status": "",
        "judge_action": "",
        "warnings": [],
    }


def _publish_node(state: GraphState) -> GraphState:
    return {
        **state,
        "response": state.get("candidate", ""),
        "chart_data": state.get("chart_data"),
    }


def _block_node(state: GraphState) -> GraphState:
    return {**state, "response": SAFE_RESPONSE, "chart_data": None}


def _after_compose(state: GraphState) -> str:
    return "judge" if state.get("composition_status") == "ready" else "end"


def _after_judge(state: GraphState) -> str:
    action = state.get("judge_action")
    if action == "approve":
        return "publish"
    if action == "correct" and state.get("revision_count", 0) == 0:
        return "revise"
    return "block"


_graph = StateGraph(GraphState)
_graph.add_node("context", _context_node)
_graph.add_node("route", _route_node)
_graph.add_node("execute", _execute_node)
_graph.add_node("compose", _compose_node)
_graph.add_node("judge", _judge_node)
_graph.add_node("revise", _prepare_revision_node)
_graph.add_node("publish", _publish_node)
_graph.add_node("block", _block_node)

_graph.set_entry_point("context")
_graph.add_edge("context", "route")
_graph.add_edge("route", "execute")
_graph.add_edge("execute", "compose")
_graph.add_conditional_edges("compose", _after_compose, {"judge": "judge", "end": END})
_graph.add_conditional_edges(
    "judge",
    _after_judge,
    {"publish": "publish", "revise": "revise", "block": "block"},
)
_graph.add_edge("revise", "execute")
_graph.add_edge("publish", END)
_graph.add_edge("block", END)

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
        "candidate": "",
        "previous_candidate": None,
        "previous_agent_results": [],
        "revision_feedback": "",
        "revision_count": 0,
        "judge_history": [],
        "judge_action": "",
        "composition_status": "",
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
        config={"configurable": {"thread_id": f"{user_id}:{session_id}"}},
    )
