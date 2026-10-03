"""Guardrail de saída: verifica a resposta antes de devolver ao usuário."""

from __future__ import annotations

import re

_CPF_RE = re.compile(r"\d{3}\.?\d{3}\.?\d{3}-?\d{2}")
_SENHA_RE = re.compile(r"\b(senha|password|secret)\b\s*[:=]\s*\S+", re.I)


def validate_output(response: str) -> dict:
    """Retorna {"ok": True, "response": response} ou {"ok": False, "reason": "..."}."""
    if not response or not response.strip():
        return {"ok": False, "reason": "Resposta vazia do agente."}

    if _CPF_RE.search(response):
        return {"ok": False, "reason": "Resposta contém dado sensível (CPF)."}

    if _SENHA_RE.search(response):
        return {"ok": False, "reason": "Resposta contém possível credencial."}

    return {"ok": True, "response": response}
