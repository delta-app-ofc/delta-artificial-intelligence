"""Guardrail de saída: redige PII e resolve tokens de anonimização da entrada."""

from __future__ import annotations

import re

from app.guardrails.input import PII_PATTERNS

_SENHA_RE = re.compile(r"\b(senha|password|secret)\b\s*[:=]\s*\S+", re.I)


def _redact_pii(text: str) -> str:
    """Remove PII que o modelo possa ter gerado diretamente na resposta."""
    for label, pattern in PII_PATTERNS:
        text = pattern.sub(f"[{label} OMITIDO]", text)
    return text


def _resolve_tokens(text: str, pii_map: dict[str, str]) -> str:
    """Substitui tokens da entrada por '[TIPO OMITIDO]' — não repete o dado original."""
    for token in pii_map:
        label = token.split("_")[1]  # [PII_CPF_abc123] → CPF
        text = text.replace(token, f"[{label} OMITIDO]")
    return text


def validate_output(response: str, pii_map: dict[str, str] | None = None) -> dict:
    """Retorna {"ok": True, "response": ...} ou {"ok": False, "reason": ...}."""
    if not response or not response.strip():
        return {"ok": False, "reason": "Resposta vazia do agente."}

    response = _redact_pii(response)

    if pii_map:
        response = _resolve_tokens(response, pii_map)

    if _SENHA_RE.search(response):
        return {"ok": False, "reason": "Resposta contém possível credencial."}

    return {"ok": True, "response": response}
