import logging
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.config import get_settings

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


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
    except Exception:
        # A rota é pública: o detalhe da configuração vai só para o log.
        logger.exception("Configuração inválida detectada no /health.")
        issues.append("Configuração inválida; consulte os logs do servidor.")
    return {"status": "ok" if not issues else "degraded", "issues": issues}
