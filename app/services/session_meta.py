"""Título, prévia e ícone da conversa, gerados pela LLM para a lista de histórico."""

from __future__ import annotations

import json
import logging
import re
import threading

from app.memory.session import (
    _PREVIEW_MAX,
    _TITLE_MAX,
    _shorten,
    session_needs_meta,
    set_session_meta,
)
from app.schemas import ICON_NAMES
from app.services import llms
from app.services.prompts import SESSION_META_PROMPT

logger = logging.getLogger(__name__)

_in_flight: set[str] = set()
_in_flight_lock = threading.Lock()

ICONS = ICON_NAMES

_PROMPT_TEXT_MAX = 1500


def _parse_meta(raw: str) -> dict | None:
    """Extrai título, prévia e ícone do JSON devolvido pela LLM. Devolve None se o JSON for
    inválido ou faltar título ou prévia; ícone desconhecido vira `general`.
    """
    match = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None

    title = _shorten(str(data.get("title") or ""), _TITLE_MAX)
    preview = _shorten(str(data.get("preview") or ""), _PREVIEW_MAX)
    if not title or not preview:
        return None

    icon = data.get("icon")
    return {"title": title, "preview": preview, "icon": icon if icon in ICONS else "general"}


def generate_session_meta(question: str, answer: str) -> dict | None:
    """Pede à LLM rápida título, prévia e ícone. Retorna None se não conseguir."""
    model = llms.llm_rapido
    if model is None:
        return None

    prompt = SESSION_META_PROMPT.format(
        icons=", ".join(ICONS),
        question=question[:_PROMPT_TEXT_MAX],
        answer=answer[:_PROMPT_TEXT_MAX],
    )
    reply = model.invoke(prompt)
    content = reply.content if hasattr(reply, "content") else str(reply)
    return _parse_meta(content if isinstance(content, str) else str(content))


def refresh_session_meta(user_id: int, session_id: str, question: str, answer: str) -> None:
    """Gera e grava título, prévia e ícone se a sessão ainda não os tem.

    Nunca levanta erro: sem metadados, a listagem usa o início das mensagens.
    Se a mesma sessão já está sendo processada, não chama a LLM de novo.
    """
    with _in_flight_lock:
        if session_id in _in_flight:
            return
        _in_flight.add(session_id)
    try:
        if not session_needs_meta(user_id, session_id):
            return
        meta = generate_session_meta(question, answer)
        if meta is None:
            return
        set_session_meta(user_id, session_id, meta["title"], meta["preview"], meta["icon"])
    except Exception as exc:
        logger.warning("Metadados da sessão não gerados: %s", type(exc).__name__)
    finally:
        with _in_flight_lock:
            _in_flight.discard(session_id)
