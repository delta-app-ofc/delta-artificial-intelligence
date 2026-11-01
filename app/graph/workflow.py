"""Workflow dos agentes Delta, compartilhado pelo chat e pelo console de testes."""
from __future__ import annotations

import contextvars
import json
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from time import perf_counter
from typing import Iterator

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.agents.judge import JudgeAgent, JudgeInput, JudgeResult, SAFE_RESPONSE
from app.graph.context import build_context
from app.graph.router import AGENT_REGISTRY, AgentNotImplemented, classify, load_agent
from app.graph.state import AgentOutput, GraphState
from app.graph.synthesis import synthesize
from app.guardrails.input import classify_input, validate_input_rules
from app.guardrails.output import (
    chart_mentions_other_user,
    hide_technical_details,
    validate_output,
    validate_ownership,
)
from app.memory.session import append_turn, load_history_validated, to_chat_messages
from app.observability.diagnostics import (
    Trace,
    capture,
    component,
    current_trace,
    safe_error,
)
from app.observability.progress import (
    plan_label,
    report_agent_started,
    reset_progress_sink,
    set_progress_sink,
)
from app.graph.profile import (
    allowed_agents,
    greeting_response,
    no_agent_response,
    resolve_access_kind,
    unavailable_agent_message,
)
from app.services.session_meta import refresh_session_meta

RECENT_TURNS = 6
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
    checked = validate_output(value)
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


def _reject_input(reason: str) -> dict:
    if trace := current_trace():
        trace.event(
            "guardrail.rejected",
            component="input_guard",
            operation="validate",
            status="rejected",
            metadata={"phase": "input_guard", "outcome": "input_rejected"},
        )
    return {"response": reason or "Mensagem bloqueada.", "pii_map": {}, "_blocked": True}


def _guardrail_input_node(state: GraphState) -> dict:
    """Regras instantâneas da entrada; o classificador LLM roda em paralelo na etapa seguinte."""
    with component("input_guard"):
        result = validate_input_rules(state["user_id"], state["question"])
    if not result["ok"]:
        return _reject_input(result.get("reason", ""))
    return {"question": result["message"],
            "messages": [{"role": "human", "content": result["message"]}],
            "pii_map": result.get("pii_map") or {}, "_blocked": False}


def _guardrail_llm_node(state: GraphState) -> dict:
    with component("input_guard"):
        blocked = classify_input(state["question"])
    if blocked is not None:
        return _reject_input(blocked.get("reason", ""))
    return {"_blocked": False}


def _after_guardrail_input(state: GraphState) -> str:
    return END if state.get("_blocked") else "prepare"


def _context_node(state: GraphState) -> dict:
    with component("context"):
        # O perfil (PostgreSQL) e o histórico/memória (MongoDB, Qdrant) não dependem um do outro.
        with ThreadPoolExecutor(max_workers=2) as pool:
            profile = pool.submit(contextvars.copy_context().run, resolve_access_kind, state["user_id"])
            context = build_context(
                state["user_id"], state["session_id"], state["question"], state.get("_history")
            )
            context["access_kind"] = profile.result()
        return context


def _route_node(state: GraphState) -> dict:
    """Escolhe os agentes da pergunta; perfil sem agente liberado pula o roteador."""
    if allowed_agents(state.get("access_kind")) == frozenset():
        # Sem agente liberado para o perfil: nem chama o roteador.
        if trace := current_trace():
            trace.routing = {"intent": "no_profile", "complexity": "simple", "agents": []}
        return {"intent": "no_profile", "complexity": "simple", "selected_agents": [],
                "unavailable_agents": [], "agent_used": "unknown"}
    context = {
        "recent_messages": state.get("recent_messages") or _recent_messages(state),
        "relevant_memory": state.get("relevant_memory", []),
        "access_kind": state.get("access_kind"),
    }
    with component("router"):
        decision = classify(state["question"], context)
    if trace := current_trace():
        trace.routing = decision.model_dump()
        trace.selected_agents = list(decision.agents)
    return {"intent": decision.intent, "complexity": decision.complexity,
            "selected_agents": decision.agents,
            "unavailable_agents": decision.unavailable,
            "agent_used": ", ".join(decision.agents) if decision.agents else "unknown"}


_guardrail_llm_tracked = None  # definido abaixo, depois de _tracked_node
_context_tracked = None
_route_tracked = None


def _context_and_route(state: GraphState) -> dict:
    context = _context_tracked(state)
    routing = _route_tracked({**state, **context})
    return {**context, **routing}


def _prepare_node(state: GraphState) -> dict:
    """Roda o classificador de segurança ao mesmo tempo que contexto e roteador.

    Nada executa antes do veredito: se a guarda bloquear, o resultado do roteador é descartado.
    Cada ramo usa uma cópia do contexto da requisição, para o rastreamento enxergar os dois.
    """
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        guard = pool.submit(contextvars.copy_context().run, _guardrail_llm_tracked, state)
        prepared = pool.submit(contextvars.copy_context().run, _context_and_route, state)
        verdict = guard.result()
        if verdict.get("_blocked"):
            return verdict
        return {**prepared.result(), **verdict}
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _after_prepare(state: GraphState) -> str:
    return END if state.get("_blocked") else "execute"


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
    access_kind: str | None = None,
) -> dict:
    """Executa o mesmo especialista usado pelas abas individuais e pelo grafo."""
    trace = current_trace()
    try:
        agent = load_agent(name, user_id, access_kind)
    except AgentNotImplemented:
        if trace:
            trace.skipped_agents.append(name)
            trace.warnings.append(f"Agente {name} pendente; etapa ignorada.")
            trace.event(
                "agent.skipped",
                component=name,
                operation="load_agent",
                status="skipped",
                metadata={"outcome": "not_implemented"},
            )
        output = AgentOutput(agent=name, status="skipped", answer="",
                             warnings=[f"Agente {name} ainda não implementado."])
        return output.model_dump()
    except Exception as error:
        if trace:
            trace.error(name, error, operation="load_agent")
        output = AgentOutput(agent=name, status="error", answer="",
                             warnings=[safe_error(error)])
        return output.model_dump()

    try:
        with component(name):
            if trace:
                trace.executed_agents.append(name)
            report_agent_started(name, access_kind)
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
    except Exception as error:
        output = AgentOutput(agent=name, status="error", answer="",
                             warnings=[safe_error(error)])
    return output.model_dump()


def _execute_node(state: GraphState) -> dict:
    """Executa os agentes selecionados em ordem, repassando as respostas anteriores como contexto.
    Agente desconhecido ou fora do perfil vira aviso; numa revisão, cada agente recebe o parecer
    do Juiz e o resultado anterior.
    """
    question = state["question"]
    history = _recent_messages(state)
    if history:
        transcript = "\n".join(f"{message['role']}: {message['content']}" for message in history)
        question += f"\n\nConversa recente:\n{transcript}"

    results = []
    warnings = list(state.get("warnings", []))
    revision_count = state.get("revision_count", 0)
    allowed = allowed_agents(state.get("access_kind"))
    for name in state.get("selected_agents", []):
        if allowed is not None and name not in allowed:
            warnings.append(f"Agente {name} não se aplica ao perfil da conta; ignorado.")
            if trace := current_trace():
                trace.skipped_agents.append(name)
            continue
        if name not in AGENT_REGISTRY:
            warnings.append(f"Agente desconhecido ignorado: {name}")
            if trace := current_trace():
                trace.skipped_agents.append(name)
                trace.event(
                    "agent.skipped",
                    component="execute",
                    operation="unknown_agent",
                    status="skipped",
                    metadata={"outcome": "unknown_agent"},
                )
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
            access_kind=state.get("access_kind"),
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
    """Une as respostas quando mais de um agente teve sucesso; com menos de dois, não altera nada."""
    results = state.get("agent_results", [])
    successes = [result for result in results
                 if result.get("status") == "success" and result.get("answer")]
    if len(successes) < 2:
        return {}
    with component("synthesis"):
        return synthesize(state["question"], successes, state.get("access_kind")) or {}


def _respond_node(state: GraphState) -> dict:
    """Define a resposta final: mensagem fixa para violação de privacidade, saudação ou pergunta
    sem agente; senão, a resposta do agente (ou a união delas) e o primeiro gráfico disponível.
    """
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
            access_kind = state.get("access_kind")
            if state.get("intent") == "greeting":
                response = greeting_response(access_kind)
            else:
                response = (unavailable_agent_message(state.get("unavailable_agents", []))
                            or no_agent_response(access_kind))
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
    """Pede ao Agente Juiz a avaliação da candidata e decide a ação: aprovar, corrigir (uma única
    vez) ou bloquear. Juiz indisponível conta como rejeição.
    """
    candidate = state.get("candidate", "")
    revision_count = state.get("revision_count", 0)
    agent_results = state.get("agent_results", [])
    context = {
        "access_kind": state.get("access_kind"),
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
            history = state.get("judge_history", [])
            previous_result = history[-1]["judge"] if revision_count and history else None
            result = JudgeAgent().run(
                JudgeInput(
                    question=state["question"],
                    candidate=candidate,
                    agent_results=agent_results,
                    context=context,
                    chart_data=state.get("chart_data"),
                ),
                revision_count=revision_count,
                previous_result=JudgeResult.model_validate(previous_result) if previous_result else None,
            )
        judge_output = result.model_dump()
        decision, status = result.decision, result.status
    except Exception:
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
    if trace := current_trace():
        trace.event(
            "judge.decision",
            component="judge",
            operation="review",
            status="unavailable" if status == "unavailable" else "success",
            metadata={
                "outcome": action,
                "revision_count": revision_count,
            },
        )
    return {"judge_history": history, "judge_action": action}


def _prepare_revision_node(state: GraphState) -> dict:
    last_judge = state.get("judge_history", [])[-1].get("judge", {})
    feedback = (last_judge.get("justification") or "").strip() or _REVISION_FALLBACK
    next_revision_count = state.get("revision_count", 0) + 1
    if trace := current_trace():
        trace.event(
            "judge.revision",
            component="revise",
            operation="prepare_revision",
            status="success",
            metadata={
                "phase": "revise",
                "outcome": "correction_requested",
                "revision_count": next_revision_count,
            },
        )
    return {
        "previous_candidate": state.get("candidate", ""),
        "previous_agent_results": state.get("agent_results", []),
        "revision_feedback": feedback,
        "revision_count": next_revision_count,
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
    """Aplica os guardrails de saída: troca a resposta recusada por uma mensagem segura, grava o
    turno no histórico quando a sessão persiste e descarta o gráfico de resposta recusada ou de
    outro usuário.
    """
    if state.get("_blocked"):
        return {}
    with component("output_guard"):
        result = validate_output(state.get("response") or "", state.get("pii_map") or {})
        if result["ok"]:
            ownership = validate_ownership(result["response"], state.get("user_id"))
            if not ownership["ok"]:
                result = ownership
    if not result["ok"]:
        if trace := current_trace():
            trace.event(
                "guardrail.rejected",
                component="output_guard",
                operation="validate",
                status="rejected",
                metadata={"phase": "output_guard", "outcome": "output_rejected"},
            )
        safe = "Não foi possível processar a resposta."
    else:
        safe = hide_technical_details(result["response"])

    if state.get("_persist_session", True):
        try:
            with component("session_save"):
                append_turn(state["session_id"], state["user_id"], "human", state["question"])
                append_turn(state["session_id"], state["user_id"], "assistant", safe)
        except Exception:
            pass
        else:
            # Título, prévia e ícone são gerados à parte para não atrasar a resposta.
            threading.Thread(
                target=refresh_session_meta,
                args=(state["user_id"], state["session_id"], state["question"], safe),
                daemon=True,
            ).start()

    update: dict = {"response": safe, "messages": [{"role": "assistant", "content": safe}]}
    if not result["ok"]:
        update["chart_data"] = None
    elif chart_mentions_other_user(state.get("chart_data"), state.get("user_id")):
        if trace := current_trace():
            trace.errors.append({"stage": "output_guard", "code": "chart_rejected",
                                 "message": "Gráfico com dados de outro usuário descartado."})
        update["chart_data"] = None
    return update


def _node_outcome(name: str, result: dict) -> str | None:
    if name in {"guardrail_input", "guardrail_llm"}:
        return "input_rejected" if result.get("_blocked") else "accepted"
    if name == "execute":
        statuses = [item.get("status") for item in result.get("agent_results", [])]
        if not statuses:
            return "no_agents"
        if all(status == "success" for status in statuses):
            return "all_succeeded"
        if any(status == "success" for status in statuses):
            return "partial"
        return "no_agent_succeeded"
    if name == "compose":
        status = result.get("composition_status")
        return status if status in {"ready", "bypass", "no_agents", "no_success"} else None
    if name == "judge":
        action = result.get("judge_action")
        return action if action in {"approve", "correct", "block"} else None
    if name == "revise":
        return "correction_requested"
    return None


def _tracked_node(name: str, action):
    def run(state: GraphState) -> dict:
        trace = current_trace()
        started = perf_counter()
        errors_before = len(trace.errors) if trace else 0
        if trace:
            trace.event(
                "graph.node.start",
                component=name,
                operation=name,
                status="running",
                metadata={"phase": name},
            )
        try:
            result = action(state)
        except Exception as error:
            if trace:
                record = trace.error(
                    name,
                    error,
                    operation=name,
                    metadata={"phase": name},
                )
                trace.event(
                    "graph.node.end",
                    component=name,
                    operation=name,
                    status="error",
                    duration_ms=round((perf_counter() - started) * 1000, 1),
                    metadata={
                        "phase": name,
                        "outcome": "failed",
                        "error_id": record.get("error_id"),
                    },
                )
            raise

        if trace:
            outcome = _node_outcome(name, result)
            errors_after = len(trace.errors)
            event_status = "partial" if errors_after > errors_before else "success"
            if name in {"guardrail_input", "guardrail_llm"} and result.get("_blocked"):
                event_status = "rejected"
            metadata = {"phase": name}
            if outcome:
                metadata["outcome"] = outcome
            if name in {"judge", "revise"}:
                revision_count = result.get("revision_count")
                if isinstance(revision_count, int):
                    metadata["revision_count"] = revision_count
            trace.event(
                "graph.node.end",
                component=name,
                operation=name,
                status=event_status,
                duration_ms=round((perf_counter() - started) * 1000, 1),
                metadata=metadata,
            )
        return result

    return run


_graph = StateGraph(GraphState)
_graph.add_node("guardrail_input", _tracked_node("guardrail_input", _guardrail_input_node))
_guardrail_llm_tracked = _tracked_node("guardrail_llm", _guardrail_llm_node)
_context_tracked = _tracked_node("context", _context_node)
_route_tracked = _tracked_node("route", _route_node)
_graph.add_node("prepare", _prepare_node)
_graph.add_node("execute", _tracked_node("execute", _execute_node))
_graph.add_node("synthesize", _tracked_node("synthesize", _synthesize_node))
_graph.add_node("respond", _tracked_node("respond", _respond_node))
_graph.add_node("compose", _tracked_node("compose", _compose_node))
_graph.add_node("judge", _tracked_node("judge", _judge_node))
_graph.add_node("revise", _tracked_node("revise", _prepare_revision_node))
_graph.add_node("publish", _tracked_node("publish", _publish_node))
_graph.add_node("block", _tracked_node("block", _block_node))
_graph.add_node("output_guard", _tracked_node("output_guard", _guardrail_output_node))
_graph.set_entry_point("guardrail_input")
_graph.add_conditional_edges("guardrail_input", _after_guardrail_input,
                             {END: END, "prepare": "prepare"})
_graph.add_conditional_edges("prepare", _after_prepare, {END: END, "execute": "execute"})
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


def _load_history(user_id: int, session_id: str) -> list[dict] | None:
    """Histórico validado da sessão; None se o MongoDB falhar (o nó de contexto tenta de novo e registra)."""
    try:
        return load_history_validated(user_id, session_id)
    except Exception as error:
        if trace := current_trace():
            trace.error("session_history", error)
        return None


def _history_from_mongo(user_id: int, session_id: str) -> list[dict]:
    history = _load_history(user_id, session_id)
    return to_chat_messages(history[-RECENT_TURNS:]) if history else []


def _start_run(
    user_id: int,
    session_id: str,
    question: str,
    *,
    persist_session: bool,
) -> tuple[GraphState, dict]:
    """Monta o estado inicial e a configuração de uma execução do grafo."""
    # O session_id nos metadados agrupa os runs filhos do LangSmith por conversa.
    config = {"configurable": {"thread_id": f"{user_id}:{session_id}"},
              "metadata": {"session_id": session_id,
                           "client": getattr(current_trace(), "client", "unknown")}}
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
    initial["_history"] = None
    if not workflow.get_state(config).values.get("messages"):
        history = _load_history(user_id, session_id)
        initial["messages"] = to_chat_messages(history[-RECENT_TURNS:]) if history else []
        # Entra no estado para o nó de contexto não ler o MongoDB uma segunda vez.
        initial["_history"] = history
    return initial, config


def _invoke_workflow(
    user_id: int,
    session_id: str,
    question: str,
    *,
    persist_session: bool,
) -> GraphState:
    initial, config = _start_run(user_id, session_id, question, persist_session=persist_session)
    try:
        return workflow.invoke(initial, config=config)
    finally:
        if persist_session:
            _forget_thread(config["configurable"]["thread_id"])


def _forget_thread(thread_id: str) -> None:
    """Apaga o estado da execução da memória do processo.

    No chat o histórico vem do MongoDB a cada pergunta; guardar o checkpoint só
    acumularia mensagens e PII em RAM sem limite. O console de testes não grava
    histórico e continua usando o checkpoint para manter a conversa.
    """
    try:
        workflow.checkpointer.delete_thread(thread_id)
    except Exception:
        pass


def run_workflow(user_id: int, session_id: str, question: str, *,
                 persist_session: bool = True) -> GraphState:
    """Executa o fluxo usando o Trace da API ou criando um para chamadas diretas."""
    if current_trace() is not None:
        return _invoke_workflow(
            user_id,
            session_id,
            question,
            persist_session=persist_session,
        )

    with capture(Trace("chat", user_id=user_id)):
        return _invoke_workflow(
            user_id,
            session_id,
            question,
            persist_session=persist_session,
        )


# Etapa mostrada ao usuário depois que cada nó termina (a próxima a acontecer).
# Só rótulos genéricos: nada da conta, da pergunta ou da resposta aparece aqui.
_CHECKING = ("checking", "Verificando a mensagem")
_STAGE_AFTER_NODE = {
    "guardrail_input": ("understanding", "Entendendo a pergunta"),
    "execute": ("composing", "Montando a resposta"),
    "synthesize": ("composing", "Montando a resposta"),
    "respond": ("composing", "Montando a resposta"),
    "compose": ("validating", "Validando a resposta"),
    "revise": ("revising", "Revisando a resposta"),
    "judge": ("finishing", "Finalizando"),
    "publish": ("finishing", "Finalizando"),
    "block": ("finishing", "Finalizando"),
}
STREAM_KEEPALIVE_SECONDS = 15


def run_workflow_events(
    user_id: int,
    session_id: str,
    question: str,
    *,
    persist_session: bool = True,
    keepalive_seconds: float = STREAM_KEEPALIVE_SECONDS,
) -> Iterator[dict]:
    """Executa o grafo e devolve eventos de progresso; o texto da resposta só vem no evento final.

    Eventos: {"type": "stage", "stage", "label"}, {"type": "keepalive"},
    {"type": "final", "state"} e {"type": "failed"}. O grafo roda numa thread própria, dentro do
    mesmo contexto de rastreamento da requisição, e entrega os eventos por uma fila.
    Depois do roteador sai um "planning" ("Vou consultar ...") e, durante a execução, um
    "working" por agente e por tool, sempre com rótulos fixos (app/observability/progress.py).
    """
    events: queue.Queue = queue.Queue()
    context = contextvars.copy_context()

    def worker() -> None:
        thread_id = f"{user_id}:{session_id}"
        try:
            def run() -> None:
                initial, config = _start_run(
                    user_id, session_id, question, persist_session=persist_session
                )
                last_label = ""
                final_state: dict = {}

                def emit(stage: str, label: str) -> None:
                    # Rótulos iguais em sequência (ex.: a mesma tool 3 vezes) aparecem uma vez só.
                    nonlocal last_label
                    if label != last_label:
                        last_label = label
                        events.put({"type": "stage", "stage": stage, "label": label})

                token = set_progress_sink(emit)
                try:
                    emit(*_CHECKING)
                    for mode, chunk in workflow.stream(
                        initial, config=config, stream_mode=["updates", "values"]
                    ):
                        if mode == "values":
                            final_state = chunk
                            continue
                        for node, update in chunk.items():
                            if node == "prepare":
                                update = update if isinstance(update, dict) else {}
                                label = plan_label(
                                    update.get("selected_agents") or [], update.get("access_kind")
                                )
                                if label:
                                    emit("planning", label)
                                continue
                            stage = _STAGE_AFTER_NODE.get(node)
                            if stage:
                                emit(*stage)
                finally:
                    reset_progress_sink(token)
                events.put({"type": "final", "state": final_state})

            if current_trace() is not None:
                run()
            else:
                with capture(Trace("chat", user_id=user_id)):
                    run()
        except Exception as error:
            if trace := current_trace():
                trace.error("stream", error)
            events.put({"type": "failed"})
        finally:
            if persist_session:
                _forget_thread(thread_id)
            events.put({"type": "end"})

    threading.Thread(target=context.run, args=(worker,), daemon=True).start()

    while True:
        try:
            item = events.get(timeout=keepalive_seconds)
        except queue.Empty:
            yield {"type": "keepalive"}
            continue
        if item["type"] == "end":
            return
        yield item
