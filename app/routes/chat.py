import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.auth import get_current_user_id
from app.graph.workflow import run_workflow, run_workflow_events
from app.memory.session import create_session, discard_empty_session, session_belongs_to_user
from app.observability.diagnostics import current_trace
from app.schemas import AUTH_ERRORS, SESSION_NOT_FOUND, ChatRequest, ChatResponse, ErrorResponse

router = APIRouter(tags=["chat"])


def _open_session(req: ChatRequest, user_id: int) -> tuple[str, bool]:
    """Valida o dono da sessão ou cria uma nova; devolve (session_id, criada_agora)."""
    if trace := current_trace():
        trace.mode, trace.user_id = "chat", user_id
    try:
        if req.session_id:
            if not session_belongs_to_user(user_id, req.session_id):
                raise HTTPException(status_code=404, detail="Sessão não encontrada.")
            return req.session_id, False
        return create_session(user_id), True
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Histórico de conversas indisponível.")


def _discard_new_session(user_id: int, session_id: str, created: bool) -> None:
    if not created:
        return
    try:
        discard_empty_session(user_id, session_id)
    except Exception:
        pass


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="Envia uma mensagem ao chatbot",
    description=(
        "Responde à pergunta do usuário autenticado. Sem session_id, o servidor cria uma conversa nova "
        "e devolve o id; com session_id, continua a conversa existente."
    ),
    responses={
        **AUTH_ERRORS,
        **SESSION_NOT_FOUND,
        503: {
            "model": ErrorResponse,
            "description": "Autenticação não configurada no servidor ou histórico de conversas indisponível.",
        },
        422: {"model": ErrorResponse, "description": "Mensagem bloqueada pelos guardrails de entrada."},
    },
)
def chat(req: ChatRequest, user_id: int = Depends(get_current_user_id)):
    session_id, created = _open_session(req, user_id)

    state = run_workflow(user_id, session_id, req.message)

    if state.get("_blocked"):
        if created:
            try:
                discard_empty_session(user_id, session_id)
            except Exception:
                pass
        raise HTTPException(status_code=422, detail=state["response"])

    return ChatResponse(
        response=state["response"],
        agents_used=state.get("selected_agents", []),
        session_id=session_id,
        chart_data=state.get("chart_data"),
    )


STREAM_EVENTS_DESCRIPTION = (
    "Eventos `text/event-stream`:\n\n"
    "- `stage`: `{\"stage\": \"checking|understanding|querying|composing|validating|revising|finishing\", "
    "\"label\": \"texto para exibir\"}`. Só indica a etapa; não traz dados da conta nem da resposta.\n"
    "- `result`: o mesmo JSON do `POST /chat`, enviado **uma vez, só depois que a resposta foi validada**.\n"
    "- `error`: `{\"status\": 422|500, \"detail\": \"...\"}` quando a mensagem é bloqueada ou o processamento falha.\n"
    "- comentário `: keep-alive` a cada 15 s sem evento.\n\n"
    "A resposta nunca é enviada aos poucos: ela só sai depois da validação."
)


@router.post(
    "/chat/stream",
    summary="Envia uma mensagem e acompanha as etapas (SSE)",
    description=(
        "Igual ao `POST /chat`, mas devolve eventos de progresso enquanto a resposta é preparada. "
        "Autenticação, dono da sessão e disponibilidade do histórico são checados antes de abrir o fluxo, "
        "com os mesmos códigos HTTP do `/chat`. Depois de aberto, o status é sempre 200 e as falhas vêm no "
        "evento `error`. Leia com `fetch` (o `EventSource` do navegador não envia o cabeçalho `Authorization`).\n\n"
        + STREAM_EVENTS_DESCRIPTION
    ),
    responses={
        200: {
            "description": "Fluxo de eventos.",
            "content": {"text/event-stream": {"schema": {"type": "string"}, "example": (
                'event: stage\ndata: {"stage": "checking", "label": "Verificando a mensagem"}\n\n'
                'event: result\ndata: {"response": "...", "agents_used": ["consumption"], '
                '"session_id": "...", "chart_data": null}\n\n'
            )}},
        },
        **AUTH_ERRORS,
        **SESSION_NOT_FOUND,
        503: {
            "model": ErrorResponse,
            "description": "Autenticação não configurada no servidor ou histórico de conversas indisponível.",
        },
    },
)
def chat_stream(req: ChatRequest, user_id: int = Depends(get_current_user_id)):
    session_id, created = _open_session(req, user_id)
    request_id = getattr(current_trace(), "request_id", None)

    def events():
        failed = True
        try:
            for item in run_workflow_events(user_id, session_id, req.message):
                kind = item["type"]
                if kind == "stage":
                    yield _sse("stage", {"stage": item["stage"], "label": item["label"]})
                elif kind == "keepalive":
                    yield ": keep-alive\n\n"
                elif kind == "final":
                    state = item["state"]
                    if state.get("_blocked"):
                        failed = False
                        _discard_new_session(user_id, session_id, created)
                        yield _sse("error", {"status": 422, "detail": state.get("response", "")})
                    elif state.get("response"):
                        failed = False
                        yield _sse("result", ChatResponse(
                            response=state["response"],
                            agents_used=state.get("selected_agents", []),
                            session_id=session_id,
                            chart_data=state.get("chart_data"),
                        ).model_dump(mode="json"))
        finally:
            if failed:
                _discard_new_session(user_id, session_id, created)
        if failed:
            yield _sse("error", {
                "status": 500,
                "detail": "Não foi possível concluir a requisição.",
                "request_id": request_id,
            })

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
