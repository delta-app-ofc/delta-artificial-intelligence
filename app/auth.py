"""Autenticação das rotas: o user_id vem do JWT emitido pelo back-end, nunca do cliente.

O back-end (delta-api-postgres) assina o token com RS256 e a chave privada dele; aqui só se confere, com a
chave PÚBLICA. O token traz `sub` (id do usuário em tb_user), `iss`, `aud` e `exp`, e o cabeçalho traz o `kid`.
Para desenvolvimento e testes existe o HS256 com um segredo compartilhado, mas nunca os dois ao mesmo tempo.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path

import jwt
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings
from app.data import db_postgres

logger = logging.getLogger(__name__)

_MIN_SECRET_LENGTH = 32
_MIN_RSA_BITS = 2048  # o back-end também exige uma chave de pelo menos 2048 bits
_LEEWAY_SECONDS = 10  # tolerância para o relógio dos servidores não estar exatamente igual
_MAX_USER_ID = 2**31 - 1  # os user_id no MongoDB são do tipo int (32 bits)
_USER_ID_RE = re.compile(r"[1-9][0-9]*")
_DEV_ENVIRONMENTS = {"development", "test"}
_bearer = HTTPBearer(auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Token ausente ou inválido.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _not_configured() -> HTTPException:
    return HTTPException(status_code=503, detail="Autenticação não configurada.")


@lru_cache(maxsize=4)
def _load_public_key(value: str):
    """Lê a chave pública RSA: o texto PEM ou o caminho do arquivo, com ou sem o prefixo `file:` do back-end."""
    text = value.strip()
    if not text.startswith("-----BEGIN"):
        path = text.removeprefix("file:")
        if path.startswith("//"):
            path = path[2:]
        if re.match(r"^/[A-Za-z]:", path):  # file:///C:/chaves/public.pem
            path = path[1:]
        text = Path(path).read_text(encoding="utf-8")
    key = serialization.load_pem_public_key(text.encode("utf-8"))
    if not isinstance(key, rsa.RSAPublicKey) or key.key_size < _MIN_RSA_BITS:
        raise ValueError("A chave pública precisa ser RSA de pelo menos 2048 bits.")
    return key


def _verification_setup(settings) -> tuple[str, object]:
    """Escolhe UMA forma de conferir o token: RS256 (produção) ou HS256 (só desenvolvimento e teste)."""
    if settings.auth_public_key:
        if not settings.auth_issuer or not settings.auth_audience:
            logger.error("AUTH_ISSUER e AUTH_AUDIENCE precisam estar definidos junto com AUTH_PUBLIC_KEY.")
            raise _not_configured()
        try:
            return "RS256", _load_public_key(settings.auth_public_key)
        except (OSError, ValueError, UnsupportedAlgorithm) as error:
            # Nunca registra o caminho nem o conteúdo da chave.
            logger.error("AUTH_PUBLIC_KEY inválida ou ilegível (%s).", type(error).__name__)
            raise _not_configured() from None

    secret = settings.jwt_secret
    if secret:
        if settings.app_env not in _DEV_ENVIRONMENTS:
            logger.error("HS256 só é permitido em desenvolvimento e teste: configure AUTH_PUBLIC_KEY.")
            raise _not_configured()
        if len(secret) < _MIN_SECRET_LENGTH:
            logger.error("JWT_SECRET com menos de %d caracteres.", _MIN_SECRET_LENGTH)
            raise _not_configured()
        return "HS256", secret

    logger.error("Autenticação sem AUTH_PUBLIC_KEY (nem JWT_SECRET, em desenvolvimento).")
    raise _not_configured()


def _ensure_active(settings, user_id: int) -> None:
    """Bloqueia usuário inexistente ou inativo; sem conseguir confirmar no banco, bloqueia também."""
    if not settings.auth_check_active:
        return
    try:
        active = db_postgres.is_user_active(user_id)
    except Exception as error:
        logger.error("Não foi possível confirmar se o usuário está ativo (%s).", type(error).__name__)
        raise HTTPException(status_code=503, detail="Autenticação indisponível.") from None
    if not active:
        raise _unauthorized()


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> int:
    """Valida o Bearer JWT e devolve o inteiro positivo do claim `sub`.

    RS256 (back-end): confere assinatura, `exp`, `iss`, `aud` e `kid`. HS256 (só desenvolvimento e teste):
    assinatura e `exp`. Depois confere se o usuário está ativo, quando AUTH_CHECK_ACTIVE está ligado.
    """
    settings = get_settings()
    algorithm, key = _verification_setup(settings)

    if credentials is None:
        raise _unauthorized()
    token = credentials.credentials

    try:
        header = jwt.get_unverified_header(token)
        # O algoritmo vem do nosso lado, nunca do token: HS256 com a chave pública como segredo é recusado.
        if header.get("alg") != algorithm:
            raise _unauthorized()
        if algorithm == "RS256":
            if settings.auth_key_id and header.get("kid") != settings.auth_key_id:
                raise _unauthorized()
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                issuer=settings.auth_issuer,
                audience=settings.auth_audience,
                leeway=_LEEWAY_SECONDS,
                options={"require": ["exp", "sub", "iss", "aud"]},
            )
        else:
            claims = jwt.decode(token, key, algorithms=["HS256"], options={"require": ["exp", "sub"]})
    except jwt.PyJWTError:
        raise _unauthorized() from None

    subject = claims["sub"]
    if not isinstance(subject, str) or not _USER_ID_RE.fullmatch(subject):
        raise _unauthorized()

    user_id = int(subject)
    if user_id > _MAX_USER_ID:
        raise _unauthorized()

    _ensure_active(settings, user_id)
    return user_id
