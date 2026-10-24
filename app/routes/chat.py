import uuid

from fastapi import APIRouter, HTTPException

from app.guardrails.input import validate_input
from app.guardrails.output import validate_output
from app.graph.workflow import run_workflow
from app.memory.session import append_turn
from app.schemas import ChatRequest, ChatResponse

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    guard = validate_input(req.user_id, req.message)
    if not guard["ok"]:
        raise HTTPException(status_code=422, detail=guard.get("reason", "Mensagem inválida."))

    anonymized = guard["message"]
    pii_map = guard.get("pii_map") or {}
    session_id = req.session_id or str(uuid.uuid4())

    state = run_workflow(
        user_id=req.user_id,
        session_id=session_id,
        question=anonymized,
        skip_guardrail_input=True,
        pii_map=pii_map,
    )

    out_guard = validate_output(state.get("response", ""), pii_map=pii_map)
    if not out_guard.get("ok"):
        raise HTTPException(status_code=500, detail="Não foi possível processar a resposta.")

    append_turn(session_id, req.user_id, "human", req.message)
    append_turn(session_id, req.user_id, "assistant", out_guard["response"])

    agents_used = state.get("selected_agents") or []

    return ChatResponse(
        response=out_guard["response"],
        agents_used=agents_used,
        session_id=session_id,
        chart_data=state.get("chart_data"),
    )
