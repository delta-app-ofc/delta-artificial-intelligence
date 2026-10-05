"""Guardrail de entrada: valida e filtra a mensagem antes de enviar ao agente."""

from __future__ import annotations

import re

_MAX_LEN = 2000

_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+instructions?", re.I),
    re.compile(r"(system|assistant)\s*:\s*", re.I),
    re.compile(r"<\s*/?system\s*>", re.I),
    re.compile(r"jailbreak", re.I),
]


def validate_input(user_id: int, message: str) -> dict:
    """Retorna {"ok": True} ou {"ok": False, "reason": "..."}."""
    if not isinstance(user_id, int) or user_id <= 0:
        return {"ok": False, "reason": "user_id inválido."}

    if not message or not message.strip():
        return {"ok": False, "reason": "Mensagem vazia."}

    if len(message) > _MAX_LEN:
        return {"ok": False, "reason": f"Mensagem excede {_MAX_LEN} caracteres."}

    for pattern in _INJECTION_PATTERNS:
        if pattern.search(message):
            return {"ok": False, "reason": "Mensagem contém padrão não permitido."}

    return {"ok": True}
