from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.config import get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"] = Field(
        ..., description="ok quando as configurações carregam sem problema; degraded caso contrário."
    )
    issues: list[str] = Field(
        ..., description="Problemas de configuração encontrados; lista vazia quando status é ok."
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Verifica a disponibilidade da API de IA",
    description="Não exige autenticação. Só confere se as configurações carregam; não testa bancos nem provedores de LLM.",
)
def health():
    issues = []
    try:
        get_settings()
    except Exception as exc:
        issues.append(str(exc))
    return {"status": "ok" if not issues else "degraded", "issues": issues}
