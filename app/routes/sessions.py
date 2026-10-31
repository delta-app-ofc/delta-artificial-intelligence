from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import get_current_user_id
from app.memory.long_term import close_session
from app.memory.session import (
    count_sessions_for_user,
    get_sessions_for_user,
    load_history_validated,
    mark_session_closed,
    session_belongs_to_user,
)
from app.schemas import (
    AUTH_ERRORS,
    SESSION_NOT_FOUND,
    ErrorResponse,
    HistoryResponse,
    SessionActionResponse,
    SessionsResponse,
)

router = APIRouter(tags=["sessions"])


def _require_owned_session(user_id: int, session_id: str) -> None:
    """Levanta 404 se a sessão não existe ou não é do usuário, sem diferenciar os dois casos."""
    if not session_belongs_to_user(user_id, session_id):
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")


@router.get(
    "/sessions",
    response_model=SessionsResponse,
    summary="Lista o histórico de conversas do usuário",
    description=(
        "Devolve as conversas do usuário autenticado, da mais recente para a mais antiga, "
        "com título, prévia e ícone. Use limit=4 na home e offset no ver todos."
    ),
    responses=AUTH_ERRORS,
)
def list_sessions(
    user_id: int = Depends(get_current_user_id),
    limit: int = Query(20, ge=1, le=100, description="Quantidade de sessões por página (1 a 100)."),
    offset: int = Query(0, ge=0, description="Quantidade de sessões a pular, para paginar."),
):
    return SessionsResponse(
        sessions=get_sessions_for_user(user_id, limit, offset),
        total=count_sessions_for_user(user_id),
    )


@router.get(
    "/sessions/{session_id}/messages",
    response_model=HistoryResponse,
    summary="Mensagens de uma conversa",
    description="Devolve todas as mensagens de uma sessão do usuário autenticado, em ordem cronológica.",
    responses={**AUTH_ERRORS, **SESSION_NOT_FOUND},
)
def get_history(session_id: str, user_id: int = Depends(get_current_user_id)):
    _require_owned_session(user_id, session_id)
    return HistoryResponse(messages=load_history_validated(user_id, session_id))


@router.post(
    "/sessions/{session_id}/close",
    response_model=SessionActionResponse,
    summary="Encerra uma conversa",
    description=(
        "Marca a sessão como fechada e grava um resumo dela na memória de longo prazo. "
        "Enviar uma nova mensagem a uma sessão fechada a reabre."
    ),
    responses={
        **AUTH_ERRORS,
        **SESSION_NOT_FOUND,
        500: {"model": ErrorResponse, "description": "Não foi possível encerrar a sessão."},
    },
)
def close(session_id: str, user_id: int = Depends(get_current_user_id)):
    """Encerra a sessão do usuário: salva o resumo na memória de longo prazo e marca a sessão como
    fechada.
    """
    _require_owned_session(user_id, session_id)
    try:
        close_session(session_id, user_id)
        mark_session_closed(user_id, session_id)
    except Exception:
        raise HTTPException(status_code=500, detail="Não foi possível encerrar a sessão.")
    return SessionActionResponse(status="ok", session_id=session_id)
