"""Console local de testes reais dos agentes e do fluxo do aplicativo."""
from __future__ import annotations

import contextvars
from functools import lru_cache
import importlib
import json
import queue
import threading
from typing import Literal
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.config import BASE_DIR, get_settings
from app.graph.router import AGENT_REGISTRY, classify
from app.graph.workflow import execute_agent, run_workflow, run_workflow_events
from app.guardrails.input import validate_input
from app.guardrails.output import validate_output
from app.memory.session import append_turn
from app.observability.diagnostics import Trace, capture, component, current_trace, public_data
from app.schemas import ErrorResponse

USER_ID = 123456789
TEST_LABEL = "teste_agentes_25_10"
FRONTEND = BASE_DIR / "frontend"


def require_playground():
    """O console é de desenvolvimento; não deve ficar público por acidente."""
    if not get_settings().playground_enabled:
        raise HTTPException(404, "Console de testes desativado.")


PLAYGROUND_DISABLED = {404: {"description": "Console de testes desativado."}}

router = APIRouter(prefix="/playground", tags=["playground"], dependencies=[Depends(require_playground)])


class PlaygroundRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=2000, description="Mensagem de teste (1 a 2000 caracteres).")
    session_id: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9_-]{1,100}$",
        description="Id livre da sessão de teste (letras, números, - e _). Omita para gerar um novo.",
    )


class AgentStatus(BaseModel):
    id: str = Field(..., description="Nome do agente, como usado na rota /playground/agents/{name}.")
    status: str = Field(..., description="available (pronto), pending (sem implementação) ou error (falha ao carregar).")
    message: str | None = Field(default=None, description="Detalhe adicional, quando houver.")


class PlaygroundConfigResponse(BaseModel):
    enabled: bool = Field(..., description="Sempre verdadeiro: com o console desativado a rota responde 404.")
    user_id: int = Field(..., description="Usuário fixo de teste usado pelo console.")
    test_label: str = Field(..., description="Rótulo da rodada de testes.")
    agents: list[AgentStatus] = Field(..., description="Agentes testáveis e a situação de cada um.")


class PlaygroundResponse(BaseModel):
    status: Literal["success", "partial", "error", "skipped"] = Field(
        ..., description="Resultado do teste: success, partial (parte das etapas falhou), error ou skipped."
    )
    response: str = Field(..., description="Resposta produzida; vazia quando o teste falhou ou foi bloqueado.")
    session_id: str = Field(..., description="Id da sessão de teste usada.")
    chart_data: dict | None = Field(default=None, description="Dados de gráfico, quando a resposta traz um.")
    agent_results: list[dict] = Field(..., description="Resultado de cada agente executado.")
    judge_results: list[dict] = Field(..., description="Avaliações do Agente Juiz (Jev), quando houve.")
    diagnostics: dict = Field(..., description="Rastro do teste: roteamento, modelos, ferramentas, avisos e erros.")


PLAYGROUND_DISABLED = {
    404: {
        "model": ErrorResponse,
        "description": "Console de testes desativado (padrão em staging e production).",
    },
}


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


@router.get(
    "/config",
    response_model=PlaygroundConfigResponse,
    summary="Configuração do console de testes",
    description=(
        "Lista os agentes testáveis e se cada um está disponível. Vem ativo em desenvolvimento e teste; "
        "em outros ambientes só com DELTA_PLAYGROUND_ENABLED=true e, como não exige autenticação, "
        "o acesso precisa ser restrito por fora."
    ),
    responses=PLAYGROUND_DISABLED,
)
def config():
    return {"enabled": True, "user_id": USER_ID, "test_label": TEST_LABEL,
            "agents": [agent_status(name) for name in (*AGENT_REGISTRY, "judge")]}


def envelope(trace, session_id, response="", chart_data=None, results=None, skipped=False,
             judge_results=None):
    statuses = [r.get("status") for r in results or []]
    rejected = any(event.get("event") == "guardrail.rejected" for event in trace.events)
    if rejected:
        status = "error"
    elif skipped or (statuses and all(s == "skipped" for s in statuses)):
        status = "skipped"
    elif trace.errors or "error" in statuses:
        routing_ok = trace.mode == "router" and bool(trace.routing) and not any(
            e["stage"] == "router" for e in trace.errors)
        status = "partial" if response and ("success" in statuses or routing_ok) else "error"
    elif "skipped" in statuses:
        status = "partial"
    else:
        status = "success"
    payload = public_data({"status": status, "response": response,
                           "chart_data": chart_data, "agent_results": results or [],
                           "judge_results": judge_results or [],
                           "diagnostics": trace.snapshot()})
    # O session_id é nosso (uuid4) e o console o reenvia na próxima mensagem. O redator de dados pessoais
    # confunde pedaços de alguns UUIDs com telefone ou CPF e o estragaria; por isso ele não passa por lá.
    payload["session_id"] = session_id
    return payload


def _judge_results(state: dict) -> list[dict]:
    summaries = []
    for entry in state.get("judge_history", []):
        judge = entry.get("judge", {})
        summaries.append({
            **judge,
            "candidate": entry.get("candidate", ""),
            "agent_results": entry.get("agent_results", []),
        })
    return summaries


def run_test(req: PlaygroundRequest, mode: str, *, workflow_runner=None):
    """Executa um teste; `workflow_runner` troca só a forma de rodar o grafo (usado pelo streaming)."""
    session_id = req.session_id or str(uuid.uuid4())
    trace = current_trace() or Trace(mode=mode)
    trace.mode, trace.user_id, trace.test_label = mode, USER_ID, TEST_LABEL
    response, chart, results, judge_results = "", None, [], []
    with capture(trace):
        try:
            with component("input_guard"):
                guard = validate_input(USER_ID, req.message)
                if not guard["ok"]:
                    trace.event("guardrail.rejected", component="input_guard", operation="validate",
                                status="rejected", metadata={"outcome": "input_rejected"})
                    trace.errors.append({"stage": "input_guard", "code": "input_rejected",
                                         "message": guard["reason"]})
                    return envelope(trace, session_id)
            message = guard["message"]
            if mode in {"chat", "judge"}:
                state = (workflow_runner or run_workflow)(USER_ID, session_id, message, persist_session=False)
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
                        trace.event("guardrail.rejected", component="output_guard", operation="validate",
                                    status="rejected", metadata={"outcome": "output_rejected"})
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
            trace.error(mode, error)
    return envelope(trace, session_id, response, chart, results, judge_results=judge_results)


@router.post(
    "/chat",
    response_model=PlaygroundResponse,
    summary="Testa o fluxo completo do chat",
    description=(
        "Executa guardrails, roteador, agentes, síntese e Juiz com o usuário fixo de teste, "
        "sem autenticação. O fluxo não grava histórico, mas a rota salva a pergunta e a resposta se o "
        "session_id informado for de uma sessão existente do usuário de teste. Erros das etapas vêm "
        "em diagnostics, com status 200."
    ),
    responses=PLAYGROUND_DISABLED,
)
def chat(req: PlaygroundRequest):
    return run_test(req, "chat")


def _event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post(
    "/chat/stream",
    summary="Testa o fluxo completo do chat e mostra as etapas (SSE)",
    description=(
        "Igual ao `POST /playground/chat`, mas devolve eventos `text/event-stream` enquanto o fluxo roda: "
        "`stage` (`{\"stage\", \"label\"}`, só rótulos fixos), `result` (o mesmo JSON do `/playground/chat`, "
        "com os diagnósticos) e `error` (`{\"status\", \"detail\"}`) se o processamento falhar. "
        "Sem autenticação, como o resto do console."
    ),
    responses={
        200: {"description": "Fluxo de eventos.", "content": {"text/event-stream": {"schema": {"type": "string"}}}},
        **PLAYGROUND_DISABLED,
    },
)
def chat_stream(req: PlaygroundRequest):
    events: queue.Queue = queue.Queue()

    def runner(user_id, session_id, message, *, persist_session=False):
        """Roda o grafo por eventos: repassa as etapas à fila e devolve o estado final."""
        final = None
        for item in run_workflow_events(user_id, session_id, message, persist_session=persist_session):
            if item["type"] == "stage":
                events.put(item)
            elif item["type"] == "final":
                final = item["state"]
            elif item["type"] == "failed":
                raise RuntimeError("Falha na execução do fluxo.")
        return final or {}

    def work():
        try:
            events.put({"type": "result", "data": run_test(req, "chat", workflow_runner=runner)})
        except Exception:
            events.put({"type": "failed"})
        finally:
            events.put({"type": "end"})

    # O mesmo contexto da requisição mantém o rastreamento (X-Request-ID) do console.
    threading.Thread(target=contextvars.copy_context().run, args=(work,), daemon=True).start()

    def stream():
        while True:
            try:
                item = events.get(timeout=15)
            except queue.Empty:
                yield ": keep-alive\n\n"
                continue
            if item["type"] == "end":
                return
            if item["type"] == "stage":
                yield _event("stage", {"stage": item["stage"], "label": item["label"]})
            elif item["type"] == "result":
                yield _event("result", item["data"])
            elif item["type"] == "failed":
                yield _event("error", {"status": 500, "detail": "Não foi possível concluir a execução."})

    return StreamingResponse(
        stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/router",
    response_model=PlaygroundResponse,
    summary="Testa só o roteador",
    description="Mostra quais agentes o roteador escolheria para a mensagem, sem executá-los.",
    responses=PLAYGROUND_DISABLED,
)
def test_router(req: PlaygroundRequest):
    return run_test(req, "router")


@router.post(
    "/agents/{name}",
    response_model=PlaygroundResponse,
    summary="Testa um agente isolado",
    description="Executa só o agente informado (consumption, forecast, leak, habits, rag ou judge).",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "Console de testes desativado ou agente de teste desconhecido.",
        },
    },
)
def test_agent(name: str, req: PlaygroundRequest):
    if name not in {*AGENT_REGISTRY, "judge"}:
        raise HTTPException(404, "Agente de teste desconhecido.")
    return run_test(req, name)


@router.get("/observability", summary="Métricas de observabilidade do console",
            description="Mesmo resumo de /observability/summary, sem token, para a aba Monitor.",
            responses=PLAYGROUND_DISABLED)
def observability_summary():
    from app.routes.monitor import build_summary
    return public_data(build_summary())


@router.get("/observability/report.pdf", summary="Relatório de observabilidade em PDF",
            responses=PLAYGROUND_DISABLED, response_class=Response)
def observability_report():
    from app.routes.monitor import pdf_response
    return pdf_response()


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
