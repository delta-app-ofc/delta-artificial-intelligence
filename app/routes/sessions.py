from fastapi import APIRouter, HTTPException

from app.memory.long_term import close_session
from app.memory.session import get_sessions_for_user, load_history_validated
from app.schemas import HistoryResponse, SessionActionResponse, SessionsResponse

router = APIRouter(tags=["sessions"])


@router.get("/users/{user_id}/sessions", response_model=SessionsResponse)
def list_sessions(user_id: int):
    return SessionsResponse(sessions=get_sessions_for_user(user_id))


@router.get("/sessions/{session_id}/messages", response_model=HistoryResponse)
def get_history(session_id: str, user_id: int):
    return HistoryResponse(messages=load_history_validated(user_id, session_id))


@router.post("/sessions/{session_id}/close", response_model=SessionActionResponse)
def close(session_id: str, user_id: int):
    try:
        close_session(session_id, user_id)
    except Exception:
        raise HTTPException(status_code=500, detail="Não foi possível encerrar a sessão.")
    return SessionActionResponse(status="ok", session_id=session_id)
