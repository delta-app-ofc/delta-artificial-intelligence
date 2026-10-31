import logging

from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_user_id
from app.graph.workflow import run_workflow
from app.memory.session import create_session, discard_empty_session, session_belongs_to_user
from app.observability.diagnostics import current_trace
from app.schemas import AUTH_ERRORS, SESSION_NOT_FOUND, ChatRequest, ChatResponse, ErrorResponse

router = APIRouter(tags=["chat"])
logger = logging.getLogger(__name__)


def _discard_new_session(user_id: int, session_id: str) -> None:
    """Remove a sessão recém-criada que ficou sem mensagens; falha na remoção só vai para o log."""
    try:
        discard_empty_session(user_id, session_id)
    except Exception as exc:
        logger.warning("Sessão vazia não removida: %s", type(exc).__name__)


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
    created = False
    if trace := current_trace():
        trace.mode, trace.user_id = "chat", user_id
    try:
        if req.session_id:
            if not session_belongs_to_user(user_id, req.session_id):
                raise HTTPException(status_code=404, detail="Sessão não encontrada.")
            session_id = req.session_id
        else:
            session_id = create_session(user_id)
            created = True
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Histórico de conversas indisponível.")

    try:
        state = run_workflow(user_id, session_id, req.message)
    except Exception:
        if created:
            _discard_new_session(user_id, session_id)
        raise

    if state.get("_blocked"):
        if created:
            _discard_new_session(user_id, session_id)
        raise HTTPException(status_code=422, detail=state["response"])

    return ChatResponse(
        response=state["response"],
        agents_used=state.get("selected_agents", []),
        session_id=session_id,
        chart_data=state.get("chart_data"),
    )
