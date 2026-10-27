"""Autenticação das rotas: o user_id vem do JWT emitido pelo back-end, nunca do cliente."""

from __future__ import annotations

import logging

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings

logger = logging.getLogger(__name__)

_ALGORITHM = "HS256"
_MIN_SECRET_LENGTH = 32
_bearer = HTTPBearer(auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Token ausente ou inválido.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> int:
    """Valida o Bearer JWT (HS256, com `exp`) e devolve o inteiro do claim `sub`."""
    secret = get_settings().jwt_secret
    if not secret or len(secret) < _MIN_SECRET_LENGTH:
        logger.error("JWT_SECRET ausente ou com menos de %d caracteres.", _MIN_SECRET_LENGTH)
        raise HTTPException(status_code=503, detail="Autenticação não configurada.")

    if credentials is None:
        raise _unauthorized()

    try:
        claims = jwt.decode(
            credentials.credentials,
            secret,
            algorithms=[_ALGORITHM],
            options={"require": ["exp", "sub"]},
        )
        user_id = int(claims["sub"])
    except (jwt.PyJWTError, ValueError, TypeError):
        raise _unauthorized() from None

    if user_id <= 0:
        raise _unauthorized()

    return user_id
