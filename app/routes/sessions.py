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
from app.schemas import HistoryResponse, SessionActionResponse, SessionsResponse

router = APIRouter(tags=["sessions"])


def _require_owned_session(user_id: int, session_id: str) -> None:
    if not session_belongs_to_user(user_id, session_id):
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")


@router.get("/sessions", response_model=SessionsResponse)
def list_sessions(
    user_id: int = Depends(get_current_user_id),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return SessionsResponse(
        sessions=get_sessions_for_user(user_id, limit, offset),
        total=count_sessions_for_user(user_id),
    )


@router.get("/sessions/{session_id}/messages", response_model=HistoryResponse)
def get_history(session_id: str, user_id: int = Depends(get_current_user_id)):
    _require_owned_session(user_id, session_id)
    return HistoryResponse(messages=load_history_validated(user_id, session_id))


@router.post("/sessions/{session_id}/close", response_model=SessionActionResponse)
def close(session_id: str, user_id: int = Depends(get_current_user_id)):
    _require_owned_session(user_id, session_id)
    try:
        close_session(session_id, user_id)
        mark_session_closed(user_id, session_id)
    except Exception:
        raise HTTPException(status_code=500, detail="Não foi possível encerrar a sessão.")
    return SessionActionResponse(status="ok", session_id=session_id)
