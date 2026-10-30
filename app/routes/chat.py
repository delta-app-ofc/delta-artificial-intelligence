from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_user_id
from app.graph.workflow import run_workflow
from app.memory.session import create_session, discard_empty_session, session_belongs_to_user
from app.schemas import AUTH_ERRORS, SESSION_NOT_FOUND, ChatRequest, ChatResponse, ErrorResponse

router = APIRouter(tags=["chat"])


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
    created = False
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

    state = run_workflow(user_id, session_id, req.message)

    if state.get("_blocked"):
        if created:
            try:
                discard_empty_session(user_id, session_id)
            except Exception:
                pass
        raise HTTPException(status_code=422, detail=state["response"])

    return ChatResponse(
        response=state["response"],
        agents_used=state.get("selected_agents", []),
        session_id=session_id,
        chart_data=state.get("chart_data"),
    )
