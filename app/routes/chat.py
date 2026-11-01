import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.auth import get_current_user_id
from app.graph.profile import resolve_access_kind
from app.graph.suggestions import initial_suggestions, suggest_next_questions
from app.graph.workflow import run_workflow, run_workflow_events
from app.memory.session import create_session, discard_empty_session, session_belongs_to_user
from app.observability.diagnostics import current_trace
from app.schemas import (
    AUTH_ERRORS,
    SESSION_NOT_FOUND,
    ChatRequest,
    ChatResponse,
    ErrorResponse,
    SuggestionsResponse,
)

router = APIRouter(tags=["chat"])
logger = logging.getLogger(__name__)


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
    """Remove a sessão recém-criada que ficou sem mensagens; falha na remoção só vai para o log."""
    if not created:
        return
    try:
        discard_empty_session(user_id, session_id)
    except Exception as exc:
        logger.warning("Sessão vazia não removida: %s", type(exc).__name__)


def _suggestions(user_id: int, state: dict, asked: str) -> list[str]:
    """Sugestões após uma resposta; qualquer falha ao descobrir o perfil só deixa a lista simples."""
    try:
        access_kind = state.get("access_kind") or resolve_access_kind(user_id)
    except Exception:
        access_kind = None
    return suggest_next_questions(state.get("selected_agents", []), access_kind, asked)


@router.get(
    "/chat/suggestions",
    response_model=SuggestionsResponse,
    summary="Perguntas sugeridas para começar a conversa",
    description="Devolve até 3 perguntas iniciais de acordo com o perfil da conta autenticada.",
    responses={**AUTH_ERRORS},
)
def chat_suggestions(user_id: int = Depends(get_current_user_id)):
    try:
        access_kind = resolve_access_kind(user_id)
    except Exception:
        access_kind = None
    return SuggestionsResponse(suggestions=initial_suggestions(access_kind))


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
    """Responde à pergunta do usuário autenticado, criando a sessão quando `session_id` não vem.
    Mensagem bloqueada pelos guardrails devolve 422 e não deixa a sessão criada por esta
    chamada.
    """
    session_id, created = _open_session(req, user_id)

    try:
        state = run_workflow(user_id, session_id, req.message)
    except Exception:
        _discard_new_session(user_id, session_id, created)
        raise

    if state.get("_blocked"):
        _discard_new_session(user_id, session_id, created)
        raise HTTPException(status_code=422, detail=state["response"])

    return ChatResponse(
        response=state["response"],
        agents_used=state.get("selected_agents", []),
        session_id=session_id,
        chart_data=state.get("chart_data"),
        suggestions=_suggestions(user_id, state, req.message),
    )


STREAM_EVENTS_DESCRIPTION = (
    "Eventos `text/event-stream`:\n\n"
    "- `stage`: `{\"stage\": \"checking|understanding|planning|working|composing|validating|revising|finishing\", "
    "\"label\": \"texto para exibir\"}`. `planning` diz o que será consultado (\"Vou consultar o seu consumo e a "
    "previsão de consumo\") e `working` acompanha cada consulta. Os textos são fixos e não trazem dados da conta, "
    "da pergunta nem da resposta.\n"
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
                            suggestions=_suggestions(user_id, state, req.message),
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
