"""Modelos generativos usados pelos agentes, construídos somente no primeiro uso."""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from typing import Any

import httpx
from google.genai.errors import APIError as GoogleAPIError
from google.genai.errors import ClientError as GoogleClientError
from groq import (
    APIConnectionError as GroqAPIConnectionError,
    APIError as GroqAPIError,
)
from langchain_core.runnables import Runnable
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError
from langchain_groq import ChatGroq

from app.config import get_settings, validate_llm_config

__all__ = [
    "EMBEDDING_MODEL_NAME",
    "LLMProviderError",
    "LLMUnavailableError",
    "clear_llm_cache",
    "llm_especialista",  # noqa: F822
    "llm_gemini",  # noqa: F822
    "llm_groq_especialista",  # noqa: F822
    "llm_rapido",  # noqa: F822
]

# Este nome é mantido para compatibilidade. O retriever ainda não foi implementado.
EMBEDDING_MODEL_NAME = "gemini-embedding-2-preview"

_PUBLIC_UNAVAILABLE_MESSAGE = "O serviço de linguagem está indisponível no momento."
_TRANSIENT_HTTP_CODES = {408, 429}


class LLMUnavailableError(RuntimeError):
    """Erro seguro quando os provedores configurados não respondem."""


class LLMProviderError(RuntimeError):
    """Erro seguro para uma solicitação rejeitada pelo provedor de LLM."""


def _read_secret(value: Any) -> Any:
    """Converte SecretStr sem incluir o valor em logs ou mensagens."""
    get_secret_value = getattr(value, "get_secret_value", None)
    if callable(get_secret_value):
        return get_secret_value()
    return value


def _status_code(error: Exception) -> int | None:
    value = getattr(error, "status_code", None)
    if value is None:
        value = getattr(error, "code", None)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _is_transient_provider_error(error: Exception) -> bool:
    """Reconhece somente falhas de transporte, limite ou indisponibilidade."""
    if isinstance(
        error,
        (httpx.TimeoutException, httpx.ConnectError, GroqAPIConnectionError),
    ):
        return True

    status_code = _status_code(error)
    if status_code is None:
        return False

    return status_code in _TRANSIENT_HTTP_CODES or 500 <= status_code < 600


def _safe_provider_error(error: Exception) -> LLMProviderError:
    """Cria uma mensagem pública sem corpo, URL, chave ou texto do SDK."""
    status_code = _status_code(error)
    if status_code is not None:
        return LLMProviderError(
            f"O provedor de linguagem rejeitou a solicitação (HTTP {status_code})."
        )
    return LLMProviderError("O provedor de linguagem rejeitou a solicitação.")


def _request_error_cause(error: Exception) -> Exception | None:
    """Retorna a causa protocolar de um erro de provedor reconhecido."""
    if isinstance(error, ChatGoogleGenerativeAIError):
        cause = error.__cause__
        if isinstance(cause, (GoogleAPIError, GoogleClientError)):
            return cause
        return None
    return error


_PROVIDER_REQUEST_ERRORS = (
    GoogleAPIError,
    ChatGoogleGenerativeAIError,
    GroqAPIError,
    httpx.TimeoutException,
    httpx.ConnectError,
)


def _invoke_model(
    model: Runnable,
    messages: Any,
    config: dict[str, Any] | None,
    kwargs: dict[str, Any],
) -> Any:
    if config is None:
        return model.invoke(messages, **kwargs)
    return model.invoke(messages, config=config, **kwargs)


def _invoke_with_fallback(
    primary: Runnable,
    fallback: Runnable | None,
    messages: Any,
    config: dict[str, Any] | None,
    kwargs: dict[str, Any],
) -> Any:
    try:
        return _invoke_model(primary, messages, config, kwargs)
    except _PROVIDER_REQUEST_ERRORS as error:
        request_error = _request_error_cause(error)
        if request_error is None:
            raise
        if not _is_transient_provider_error(request_error):
            raise _safe_provider_error(request_error) from None
        if fallback is None:
            raise LLMUnavailableError(_PUBLIC_UNAVAILABLE_MESSAGE) from None

    try:
        # A mesma lista é enviada ao segundo provedor, inclusive ToolMessages anteriores.
        return _invoke_model(fallback, messages, config, kwargs)
    except _PROVIDER_REQUEST_ERRORS as error:
        request_error = _request_error_cause(error)
        if request_error is None:
            raise
        if not _is_transient_provider_error(request_error):
            raise _safe_provider_error(request_error) from None
        raise LLMUnavailableError(_PUBLIC_UNAVAILABLE_MESSAGE) from None


class _BoundFallbackLLM:
    """Adapta modelos já vinculados às ferramentas ao contrato usado pelo runtime."""

    def __init__(self, primary: Runnable, fallback: Runnable | None) -> None:
        self._primary = primary
        self._fallback = fallback

    def invoke(
        self,
        messages: Any,
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        return _invoke_with_fallback(
            self._primary,
            self._fallback,
            messages,
            config,
            kwargs,
        )


class _FallbackLLM:
    """Mantém bind_tools disponível e aplica fallback só a falhas transitórias."""

    def __init__(self, primary: Any, fallback: Any | None) -> None:
        self._primary = primary
        self._fallback = fallback

    def bind_tools(
        self,
        tools: Sequence[Any],
        **kwargs: Any,
    ) -> _BoundFallbackLLM:
        primary = self._primary.bind_tools(tools, **kwargs)
        fallback = (
            self._fallback.bind_tools(tools, **kwargs)
            if self._fallback is not None
            else None
        )
        return _BoundFallbackLLM(primary, fallback)

    def invoke(
        self,
        messages: Any,
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        return _invoke_with_fallback(
            self._primary,
            self._fallback,
            messages,
            config,
            kwargs,
        )


def _get_retries() -> int:
    return get_settings().llm_max_retries


@lru_cache(maxsize=1)
def _get_llm_gemini() -> ChatGoogleGenerativeAI:
    validate_llm_config(provider="gemini")
    settings = get_settings()
    # langchain-google-genai encaminha `max_retries` como total de tentativas
    # do SDK Google. Somamos a chamada inicial ao limite de retries da aplicação.
    return ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        temperature=0.3,
        top_p=0.95,
        api_key=_read_secret(settings.gemini_api_key),
        max_retries=_get_retries() + 1,
        timeout=settings.llm_timeout_seconds,
        max_output_tokens=settings.llm_max_output_tokens,
    )


@lru_cache(maxsize=1)
def _get_llm_groq_especialista() -> ChatGroq:
    validate_llm_config(provider="groq_specialist")
    settings = get_settings()
    return ChatGroq(
        model=settings.groq_specialist_model,
        temperature=0.3,
        api_key=_read_secret(settings.groq_api_key),
        max_retries=_get_retries(),
        timeout=settings.llm_timeout_seconds,
        max_tokens=settings.llm_max_output_tokens,
    )


@lru_cache(maxsize=1)
def _get_llm_especialista() -> _FallbackLLM:
    validate_llm_config(provider="specialist")
    settings = get_settings()
    fallback = (
        _get_llm_groq_especialista() if settings.llm_fallback_enabled else None
    )
    return _FallbackLLM(_get_llm_gemini(), fallback)


@lru_cache(maxsize=1)
def _get_llm_rapido() -> ChatGroq:
    validate_llm_config(provider="fast")
    settings = get_settings()
    return ChatGroq(
        model=settings.groq_fast_model,
        temperature=0.0,
        api_key=_read_secret(settings.groq_api_key),
        max_retries=_get_retries(),
        timeout=settings.llm_timeout_seconds,
        max_tokens=settings.llm_max_output_tokens,
    )


def clear_llm_cache() -> None:
    """Limpa modelos em cache após recarregar settings em testes ou desenvolvimento."""
    _get_llm_especialista.cache_clear()
    _get_llm_gemini.cache_clear()
    _get_llm_groq_especialista.cache_clear()
    _get_llm_rapido.cache_clear()


_LAZY = {
    "llm_gemini": _get_llm_gemini,
    "llm_groq_especialista": _get_llm_groq_especialista,
    "llm_especialista": _get_llm_especialista,
    "llm_rapido": _get_llm_rapido,
}


def __getattr__(name: str) -> Any:
    try:
        builder = _LAZY[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    return builder()


def __dir__() -> list[str]:
    return sorted(__all__)
