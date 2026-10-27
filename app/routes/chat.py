from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_user_id
from app.graph.workflow import run_workflow
from app.memory.session import create_session, session_belongs_to_user
from app.schemas import ChatRequest, ChatResponse

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, user_id: int = Depends(get_current_user_id)):
    try:
        if req.session_id:
            if not session_belongs_to_user(user_id, req.session_id):
                raise HTTPException(status_code=404, detail="Sessão não encontrada.")
            session_id = req.session_id
        else:
            session_id = create_session(user_id)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Histórico de conversas indisponível.")

    state = run_workflow(user_id, session_id, req.message)

    if state.get("_blocked"):
        raise HTTPException(status_code=422, detail=state["response"])

    return ChatResponse(
        response=state["response"],
        agents_used=state.get("selected_agents", []),
        session_id=session_id,
        chart_data=state.get("chart_data"),
    )
