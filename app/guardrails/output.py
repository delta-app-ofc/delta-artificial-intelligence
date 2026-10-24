"""Guardrail de saída: redige PII e resolve tokens de anonimização da entrada."""

from __future__ import annotations

import re

from app.guardrails.input import PII_PATTERNS

_SENHA_RE = re.compile(r"\b(senha|password|secret)\b\s*[:=]\s*\S+", re.I)


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
