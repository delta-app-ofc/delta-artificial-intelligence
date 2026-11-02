"""Confirmação humana de gravações: leitura do "sim"/"não" e textos fixos.

O modelo nunca decide gravar. A ferramenta só propõe; o grafo pausa com interrupt() e, se o
usuário responder "sim", o código executa a gravação aqui. Nada neste módulo chama um LLM.
"""

from __future__ import annotations

import re
import unicodedata
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.config import get_settings
from app.data import db_postgres
from app.tools.forecast.tools import validate_last_bill, write_last_bill

# Tempo que uma proposta fica esperando a resposta do usuário.
CONFIRMATION_TTL_SECONDS = 600
BILL_KIND = "register_last_bill"

DECLINED_TEXT = "Tudo bem, não registrei a conta."
EXPIRED_TEXT = "A confirmação expirou e nada foi registrado. Se ainda quiser, peça o registro de novo."
UNKNOWN_ACTION_TEXT = "Não foi possível concluir essa ação. Nada foi registrado."

_MONTHS = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
           "agosto", "setembro", "outubro", "novembro", "dezembro")

# Respostas aceitas como "sim": todas as palavras precisam estar nestes dois conjuntos.
_YES_WORDS = {"sim", "s", "confirmo", "confirmado", "pode", "ok", "isso", "claro", "certo",
              "positivo", "salve", "salvar", "registre", "registrar", "combinado", "beleza"}
_FILLER_WORDS = {"por", "favor", "com", "certeza", "mesmo", "o", "a", "e", "tudo", "bem", "pra", "para"}
# Qualquer uma destas palavras já basta para recusar.
_NO_WORDS = {"nao", "n", "cancela", "cancele", "cancelar", "desisto", "desistir", "negativo",
             "esquece", "esqueca", "pare", "nunca", "jamais"}


def _words(text: str) -> list[str]:
    plain = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(char for char in plain if not unicodedata.combining(char))
    return re.findall(r"[a-z0-9]+", plain)


def parse_answer(text: str) -> bool | None:
    """True para um "sim" claro, False para um "não" e None para qualquer outra coisa.

    Na dúvida devolve None: nunca grava. Mensagens longas, com números ou com pergunta
    (por exemplo "sim, mas o valor é 150") não são confirmação.
    """
    words = _words(text or "")
    if not words or len(words) > 6 or "?" in text or any(word.isdigit() for word in words):
        return None
    if any(word in _NO_WORDS for word in words):
        return False
    if any(word in _YES_WORDS for word in words) and all(
        word in _YES_WORDS or word in _FILLER_WORDS for word in words
    ):
        return True
    return None


def new_expiry(now: datetime | None = None) -> str:
    """Instante limite da confirmação, em ISO 8601 UTC."""
    return ((now or datetime.now(timezone.utc)) + timedelta(seconds=CONFIRMATION_TTL_SECONDS)).isoformat()


def is_expired(expires_at: str | None, now: datetime | None = None) -> bool:
    try:
        limit = datetime.fromisoformat(expires_at or "")
    except (ValueError, TypeError):
        return True
    if limit.tzinfo is None:
        return True
    return (now or datetime.now(timezone.utc)) >= limit


def _brl(value: float) -> str:
    return "R$ " + f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _number(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def _month_label(iso_month: str) -> str:
    month = date.fromisoformat(iso_month)
    return f"{_MONTHS[month.month - 1]} de {month.year}"


def describe(pending: dict) -> str:
    """Pergunta mostrada ao usuário quando o grafo pausa."""
    if pending.get("kind") != BILL_KIND:
        return "Posso confirmar essa ação? Responda sim para continuar ou não para cancelar."
    params = pending["params"]
    return (
        f"Confirma o registro da conta de {_month_label(params['month'])}: "
        f"{_brl(params['total_value'])} e {_number(params['m3_value'])} m³? "
        "Responda sim para salvar ou não para cancelar."
    )


def execute_pending(pending: dict, user_id: int, today: date) -> str:
    """Executa a gravação confirmada e devolve o texto final para o usuário.

    Valida de novo tudo o que veio da proposta e confere o perfil: a decisão não depende
    do que o modelo disse, e o user_id é o do usuário autenticado.
    """
    if pending.get("kind") != BILL_KIND:
        return UNKNOWN_ACTION_TEXT
    if not get_settings().bill_registration_enabled:
        return "O cadastro da conta está desativado. Nada foi registrado."
    if db_postgres.get_user_access_kind(user_id) != "residential":
        return "O cadastro da conta só está disponível para contas residenciais."
    params = pending["params"]
    error, parsed = validate_last_bill(params["month"], params["total_value"], params["m3_value"], today)
    if error is not None:
        return error["message"]
    result: dict[str, Any] = write_last_bill(user_id, *parsed)
    if result["status"] == "ok":
        return (
            f"Pronto! Registrei a conta de {_month_label(params['month'])}: "
            f"{_brl(params['total_value'])} e {_number(params['m3_value'])} m³."
        )
    return result["message"]


# A trava dura só enquanto há chamadas em andamento. Isso evita acumular uma por sessão.
_SESSION_LOCKS_GUARD = threading.Lock()
_SESSION_LOCKS: dict[tuple[int, str], tuple[Any, int]] = {}


@contextmanager
def session_lock(user_id: int, session_id: str):
    """Serializa mensagens da mesma sessão neste processo, inclusive entre chat e streaming.

    Duas confirmações simultâneas não podem retomar o mesmo checkpoint. O contador
    mantém a trava viva enquanto há chamadas esperando e a remove quando todas terminam.
    """
    key = (user_id, session_id)
    with _SESSION_LOCKS_GUARD:
        lock, count = _SESSION_LOCKS.get(key, (threading.Lock(), 0))
        _SESSION_LOCKS[key] = (lock, count + 1)
    try:
        with lock:
            yield
    finally:
        with _SESSION_LOCKS_GUARD:
            _, count = _SESSION_LOCKS[key]
            if count == 1:
                del _SESSION_LOCKS[key]
            else:
                _SESSION_LOCKS[key] = (lock, count - 1)
