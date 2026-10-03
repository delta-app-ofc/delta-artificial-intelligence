import uuid

from fastapi import APIRouter, HTTPException

from app.guardrails.input import validate_input
from app.guardrails.output import validate_output
from app.graph.workflow import run_workflow
from app.memory.session import append_turn
from app.schemas import ChatRequest, ChatResponse

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    guard = validate_input(req.user_id, req.message)
    if not guard["ok"]:
        raise HTTPException(status_code=422, detail=guard["reason"])

    session_id = req.session_id or str(uuid.uuid4())

    state = run_workflow(
        user_id=req.user_id,
        session_id=session_id,
        question=req.message,
    )

    out_guard = validate_output(state["response"])
    if not out_guard["ok"]:
        raise HTTPException(status_code=500, detail=out_guard["reason"])

    append_turn(session_id, req.user_id, "human", req.message)
    append_turn(session_id, req.user_id, "assistant", state["response"])

    return ChatResponse(
        response=state["response"],
        agent_used=state.get("agent_used", ""),
        session_id=session_id,
        chart_data=state.get("chart_data"),
    )
