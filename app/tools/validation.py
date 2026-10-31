"""Validações compartilhadas pelas tools dos agentes."""

from __future__ import annotations

# Janela máxima de consulta, igual ao limite já usado pelo agente de consumo.
MAX_WINDOW_DAYS = 366


def validate_user_id(user_id: object) -> int:
    """Exige o user_id confiável (inteiro positivo) recebido de quem constrói as tools."""
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise ValueError("user_id deve ser um inteiro positivo recebido do chamador.")
    return user_id


def days_error(days: object, name: str = "days") -> dict | None:
    """Retorna a resposta de erro da tool quando a janela não é um inteiro de 1 a 366."""
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= MAX_WINDOW_DAYS:
        return {
            "status": "error",
            "message": f"{name} deve ser um número inteiro entre 1 e {MAX_WINDOW_DAYS}.",
        }
    return None
