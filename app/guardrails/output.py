"""Guardrail de saída: redige PII, resolve tokens de anonimização e barra dados de outro usuário."""

from __future__ import annotations

import re
from typing import Any

from app.guardrails.input import PII_PATTERNS

_SENHA_RE = re.compile(r"\b(senha|password|secret)\b\s*[:=]\s*\S+", re.I)

# Formas como uma resposta pode citar o identificador de um usuário.
_USER_ID_PATTERNS = [
    re.compile(r"user[_\s-]?id\W{0,3}(\d+)", re.I),
    re.compile(r"usu[aá]rio\s+(?:n[º°o]\.?\s*|id\s*|#)?(\d+)", re.I),
    re.compile(r"id\s+(?:do|de)\s+usu[aá]rio\W{0,3}(\d+)", re.I),
]


def mentions_other_user(text: str, user_id: int | None) -> bool:
    """Indica se o texto cita o id de um usuário diferente de user_id."""
    if user_id is None:
        return False
    for pattern in _USER_ID_PATTERNS:
        for match in pattern.finditer(text):
            if int(match.group(1)) != user_id:
                return True
    return False


def chart_mentions_other_user(chart_data: Any, user_id: int | None) -> bool:
    """Indica se os dados do gráfico trazem um campo user_id diferente de user_id."""
    if user_id is None:
        return False
    if isinstance(chart_data, dict):
        for key, value in chart_data.items():
            if key == "user_id" and value != user_id:
                return True
            if chart_mentions_other_user(value, user_id):
                return True
    elif isinstance(chart_data, (list, tuple)):
        return any(chart_mentions_other_user(item, user_id) for item in chart_data)
    return False


def validate_output(response: str, pii_map: dict[str, str] | None = None) -> dict:
    """Retorna {"ok": True, "response": ...} ou {"ok": False, "reason": ...}."""

    if not response or not response.strip():
        return {"ok": False, "reason": "Resposta vazia do agente."}

    for label, pattern in PII_PATTERNS:
        response = pattern.sub(f"[{label} OMITIDO]", response)

    for token in pii_map or {}:
        label = token.split("_")[1]  # [PII_CPF_abc123] → CPF
        response = response.replace(token, f"[{label} OMITIDO]")

    if _SENHA_RE.search(response):
        return {"ok": False, "reason": "Resposta contém possível credencial."}

    return {"ok": True, "response": response}


def validate_ownership(response: str, user_id: int | None) -> dict:
    """Segunda barreira de isolamento: barra respostas que citem o id de outro usuário.

    Só age se uma consulta trouxer, por falha, dados que não são do usuário atual.
    """
    if mentions_other_user(response, user_id):
        return {"ok": False, "reason": "Resposta cita dados de outro usuário."}
    return {"ok": True, "response": response}
