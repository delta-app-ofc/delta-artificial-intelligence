from fastapi import APIRouter, HTTPException

from app.memory.session import get_sessions_for_user, load_history
from app.memory.long_term import close_session

router = APIRouter()


@router.get("/sessions/{user_id}")
def list_sessions(user_id: int):
    return {"sessions": get_sessions_for_user(user_id)}


@router.get("/sessions/{session_id}/history")
def get_history(session_id: str):
    return {"messages": load_history(session_id)}


@router.post("/sessions/{session_id}/close")
def close(session_id: str, user_id: int):
    try:
        close_session(session_id, user_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"status": "ok", "session_id": session_id}
