import uuid

from fastapi import APIRouter, HTTPException

from app.graph.workflow import run_workflow
from app.observability.diagnostics import current_trace
from app.schemas import ChatRequest, ChatResponse

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    if trace := current_trace():
        trace.mode, trace.user_id = "chat", req.user_id
    session_id = req.session_id or str(uuid.uuid4())
    state = run_workflow(req.user_id, session_id, req.message)

    if state.get("_blocked"):
        raise HTTPException(status_code=422, detail=state["response"])

    return ChatResponse(
        response=state["response"],
        agents_used=state.get("selected_agents", []),
        session_id=session_id,
        chart_data=state.get("chart_data"),
    )
