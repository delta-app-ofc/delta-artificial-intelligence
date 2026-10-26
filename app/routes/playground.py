"""Console local de testes reais dos agentes e do fluxo do aplicativo."""
from __future__ import annotations

from functools import lru_cache
import importlib
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from app.config import BASE_DIR, get_settings
from app.graph.router import AGENT_REGISTRY, classify
from app.graph.workflow import execute_agent, run_workflow
from app.guardrails.input import validate_input
from app.guardrails.output import validate_output
from app.memory.session import append_turn
from app.observability.diagnostics import Trace, capture, component, public_data

USER_ID = 12345679
TEST_LABEL = "teste_agentes_25_10"
FRONTEND = BASE_DIR / "frontend"


def require_playground():
    """O console é de desenvolvimento; não deve ficar público por acidente."""
    if not get_settings().playground_enabled:
        raise HTTPException(404, "Console de testes desativado.")


router = APIRouter(prefix="/playground", tags=["playground"], dependencies=[Depends(require_playground)])


class PlaygroundRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,100}$")


def agent_status(name: str) -> dict:
    if name == "judge":
        return {"id": name, "status": "available",
                "message": "Executa o fluxo completo do chat e inclui a avaliação Jev."}
    path = AGENT_REGISTRY[name]
    module_path, class_name = path.rsplit(".", 1)
    try:
        cls = getattr(importlib.import_module(module_path), class_name, None)
    except Exception:
        return {"id": name, "status": "error", "message": "Falha ao carregar o módulo; veja o teste individual."}
    status = "available" if cls is not None and callable(getattr(cls, "run", None)) else "pending"
    return {"id": name, "status": status}


@router.get("/config")
def config():
    return {"enabled": True, "user_id": USER_ID, "test_label": TEST_LABEL,
            "agents": [agent_status(name) for name in (*AGENT_REGISTRY, "judge")]}


def envelope(trace, session_id, response="", chart_data=None, results=None, skipped=False,
             judge_results=None):
    statuses = [r.get("status") for r in results or []]
    if skipped or (statuses and all(s == "skipped" for s in statuses)):
        status = "skipped"
    elif trace.errors or "error" in statuses:
        routing_ok = trace.mode == "router" and bool(trace.routing) and not any(
            e["stage"] == "router" for e in trace.errors)
        status = "partial" if response and ("success" in statuses or routing_ok) else "error"
    elif "skipped" in statuses:
        status = "partial"
    else:
        status = "success"
    return public_data({"status": status, "response": response, "session_id": session_id,
                        "chart_data": chart_data, "agent_results": results or [],
                        "judge_results": judge_results or [],
                        "diagnostics": trace.snapshot()})


def _judge_results(state: dict) -> list[dict]:
    summaries = []
    for entry in state.get("judge_history", []):
        judge = entry.get("judge", {})
        assessment = judge.get("assessment", {})
        summaries.append({
            "decision": judge.get("decision"),
            "status": judge.get("status"),
            "severity": judge.get("severity"),
            "confidence": judge.get("confidence"),
            "reason_codes": judge.get("reason_codes", []),
            "justification": judge.get("justification", ""),
            "assessment": {
                "confidence_threshold": assessment.get("confidence_threshold"),
                "severity_probabilities": assessment.get("severity_probabilities", {}),
                "selected_probability": assessment.get("selected_probability"),
                "input_summary": assessment.get("input_summary", {}),
                "subcriteria_checked": assessment.get("subcriteria_checked", False),
                "diagnostics": assessment.get("diagnostics", {}),
            },
        })
    return summaries


def run_test(req: PlaygroundRequest, mode: str):
    session_id = req.session_id or str(uuid.uuid4())
    trace = Trace(mode=mode, user_id=USER_ID, test_label=TEST_LABEL)
    response, chart, results, judge_results = "", None, [], []
    with capture(trace):
        try:
            with component("input_guard"):
                guard = validate_input(USER_ID, req.message)
                if not guard["ok"]:
                    trace.errors.append({"stage": "input_guard", "code": "input_rejected",
                                         "message": guard["reason"]})
                    return envelope(trace, session_id)
            message = guard["message"]
            if mode in {"chat", "judge"}:
                state = run_workflow(USER_ID, session_id, message, persist_session=False)
                response, chart = state["response"], state.get("chart_data")
                results = state.get("agent_results", [])
                judge_results = _judge_results(state)
                trace.warnings.extend(state.get("warnings", []))
                if mode == "judge" and not judge_results:
                    trace.warnings.append("O fluxo não produziu uma candidata para avaliação Jev.")
            elif mode == "router":
                from app.graph.context import build_context
                with component("context"):
                    context = build_context(USER_ID, session_id, message)
                with component("router"):
                    decision = classify(message, context)
                trace.routing = decision.model_dump()
                trace.selected_agents = list(decision.agents)
                response = ("Agentes selecionados: " + ", ".join(decision.agents)
                            if decision.agents else "O roteador não selecionou nenhum agente.")
            else:
                trace.selected_agents = [mode]
                result = execute_agent(mode, USER_ID, message)
                results = [result]
                response, chart = result["answer"], result.get("chart_data")
            if response:
                with component("output_guard"):
                    out = validate_output(response, pii_map=guard["pii_map"])
                    if not out["ok"]:
                        trace.errors.append({"stage": "output_guard", "code": "output_rejected",
                                             "message": out["reason"]})
                        response, chart = "", None
                    else:
                        response = out["response"]
                if mode in {"chat", "judge"} and response:
                    try:
                        with component("session_save"):
                            append_turn(session_id, USER_ID, "human", req.message)
                            append_turn(session_id, USER_ID, "assistant", response)
                    except Exception:
                        # A resposta fica visível com erro de persistência no painel.
                        pass
        except Exception as error:
            # Erros de etapas já instrumentadas estão registrados uma única vez.
            if not any(e["code"] == type(error).__name__ for e in trace.errors):
                trace.error(mode, error)
    return envelope(trace, session_id, response, chart, results, judge_results=judge_results)


@router.post("/chat")
def chat(req: PlaygroundRequest):
    return run_test(req, "chat")


@router.post("/router")
def test_router(req: PlaygroundRequest):
    return run_test(req, "router")


@router.post("/agents/{name}")
def test_agent(name: str, req: PlaygroundRequest):
    if name not in {*AGENT_REGISTRY, "judge"}:
        raise HTTPException(404, "Agente de teste desconhecido.")
    return run_test(req, name)


@lru_cache(maxsize=1)
def plotly_bundle():
    from plotly.offline import get_plotlyjs
    return get_plotlyjs()


@router.get("/assets/plotly.min.js", include_in_schema=False)
def plotly_asset():
    return Response(plotly_bundle(), media_type="application/javascript",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/", include_in_schema=False)
def index():
    return FileResponse(FRONTEND / "index.html", headers={"Cache-Control": "no-store"})


@router.get("/{asset:path}", include_in_schema=False)
def static_asset(asset: str):
    target = (FRONTEND / asset).resolve()
    if not target.is_relative_to(FRONTEND.resolve()) or not target.is_file():
        raise HTTPException(404, "Arquivo não encontrado.")
    return FileResponse(target)
