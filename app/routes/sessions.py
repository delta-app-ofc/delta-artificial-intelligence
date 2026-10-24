from fastapi import APIRouter, HTTPException

from app.memory.session import get_sessions_for_user, load_history_validated
from app.memory.long_term import close_session
from app.schemas import HistoryResponse, MessageItem, SessionActionResponse, SessionInfo, SessionsResponse

router = APIRouter(tags=["sessions"])


@router.get("/users/{user_id}/sessions", response_model=SessionsResponse)
def list_sessions(user_id: int):
    raw = get_sessions_for_user(user_id)
    sessions = [
        SessionInfo(
            session_id=s.get("session_id", s) if isinstance(s, dict) else str(s),
            created_at=s.get("created_at") if isinstance(s, dict) else None,
        )
        for s in raw
    ]
    return SessionsResponse(sessions=sessions)


@router.get("/sessions/{session_id}/messages", response_model=HistoryResponse)
def get_history(session_id: str, user_id: int):
    raw = load_history_validated(user_id, session_id)
    messages = [
        MessageItem(
            role=m.get("role", ""),
            content=m.get("content", ""),
            timestamp=m.get("timestamp"),
        )
        for m in (raw or [])
    ]
    return HistoryResponse(messages=messages)


@router.post("/sessions/{session_id}/close", response_model=SessionActionResponse)
def close(session_id: str, user_id: int):
    try:
        close_session(session_id, user_id)
    except Exception:
        raise HTTPException(status_code=500, detail="Não foi possível encerrar a sessão.")
    return SessionActionResponse(status="ok", session_id=session_id)
