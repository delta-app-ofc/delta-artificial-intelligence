"""Modelos generativos usados pelos agentes, construídos somente no primeiro uso."""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
import sys
from time import perf_counter
from typing import Any

import httpx
from google.genai.errors import APIError as GoogleAPIError
from google.genai.errors import ClientError as GoogleClientError
from groq import (
    APIConnectionError as GroqAPIConnectionError,
    APIError as GroqAPIError,
)
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError
from langchain_groq import ChatGroq

from app.config import ConfigurationError, get_settings, validate_llm_config
from app.observability.diagnostics import (
    ModelDiagnostics,
    current_component,
    current_trace,
    fallback_call,
)

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

_PUBLIC_UNAVAILABLE_MESSAGE = "O serviço de linguagem está indisponível no momento."
_TRANSIENT_HTTP_CODES = {408, 429}


class LLMUnavailableError(RuntimeError):
    """Erro seguro quando os provedores configurados não respondem."""


class LLMProviderError(RuntimeError):
    """Erro seguro para uma solicitação rejeitada pelo provedor de LLM."""


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


class _FallbackLLM:
    """Mantém bind_tools disponível e aplica fallback só a falhas transitórias."""

    def __init__(
        self,
        primary: Any,
        fallback: Any | None,
        *,
        primary_provider: str = "google",
        primary_model: str | None = None,
        fallback_provider: str = "groq",
        fallback_model: str | None = None,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._primary_provider = primary_provider
        self._primary_model = primary_model
        self._fallback_provider = fallback_provider
        self._fallback_model = fallback_model

    def bind_tools(
        self,
        tools: Sequence[Any],
        **kwargs: Any,
    ) -> _FallbackLLM:
        primary = self._primary.bind_tools(tools, **kwargs)
        fallback = (
            self._fallback.bind_tools(tools, **kwargs)
            if self._fallback is not None
            else None
        )
        return _FallbackLLM(
            primary,
            fallback,
            primary_provider=self._primary_provider,
            primary_model=self._primary_model,
            fallback_provider=self._fallback_provider,
            fallback_model=self._fallback_model,
        )

    @staticmethod
    def _invoke_model(
        model: Any,
        messages: Any,
        invoke_kwargs: dict[str, Any],
        *,
        provider: str,
        model_name: str | None,
        fallback: bool,
    ) -> Any:
        trace = current_trace()
        component_name = current_component()
        started = perf_counter()
        metadata = {"provider": provider, "fallback": fallback}
        if model_name:
            metadata["model"] = model_name

        if trace:
            trace.event(
                "llm.start",
                component=component_name,
                operation="chat_completion",
                status="running",
                metadata=metadata,
            )
        try:
            response = model.invoke(messages, **invoke_kwargs)
        except Exception as error:
            error_record = None
            if trace:
                error_record = trace.error(
                    "llm",
                    error,
                    operation="chat_completion",
                    metadata={"provider": provider, **({"model": model_name} if model_name else {})},
                )
                failure_metadata = dict(metadata)
                failure_metadata["outcome"] = "request_failed"
                if error_record and error_record.get("error_id"):
                    failure_metadata["error_id"] = error_record["error_id"]
                trace.event(
                    "llm.end",
                    component=component_name,
                    operation="chat_completion",
                    status="error",
                    duration_ms=round((perf_counter() - started) * 1000, 1),
                    metadata=failure_metadata,
                )
            raise

        if trace:
            success_metadata = dict(metadata)
            success_metadata["outcome"] = "completed"
            trace.event(
                "llm.end",
                component=component_name,
                operation="chat_completion",
                status="success",
                duration_ms=round((perf_counter() - started) * 1000, 1),
                metadata=success_metadata,
            )
        return response

    def invoke(
        self,
        messages: Any,
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        invoke_kwargs = dict(kwargs)
        if config is not None:
            invoke_kwargs["config"] = config

        try:
            return self._invoke_model(
                self._primary,
                messages,
                invoke_kwargs,
                provider=self._primary_provider,
                model_name=self._primary_model,
                fallback=False,
            )
        except _PROVIDER_REQUEST_ERRORS as error:
            request_error = _request_error_cause(error)
            if request_error is None:
                raise
            if not _is_transient_provider_error(request_error):
                raise _safe_provider_error(request_error) from None
            if self._fallback is None:
                raise LLMUnavailableError(_PUBLIC_UNAVAILABLE_MESSAGE) from None

        if trace := current_trace():
            trace.warnings.append("O modelo principal falhou; o fallback foi acionado.")
            trace.event(
                "llm.fallback",
                component=current_component(),
                operation="chat_completion",
                status="started",
                metadata={
                    "provider": self._fallback_provider,
                    **({"model": self._fallback_model} if self._fallback_model else {}),
                    "fallback": True,
                    "outcome": "primary_transient_failure",
                },
            )

        try:
            # O fallback recebe a mesma lista, inclusive as ToolMessages anteriores.
            with fallback_call():
                return self._invoke_model(
                    self._fallback,
                    messages,
                    invoke_kwargs,
                    provider=self._fallback_provider,
                    model_name=self._fallback_model,
                    fallback=True,
                )
        except _PROVIDER_REQUEST_ERRORS as error:
            request_error = _request_error_cause(error)
            if request_error is None:
                raise
            if not _is_transient_provider_error(request_error):
                raise _safe_provider_error(request_error) from None
            raise LLMUnavailableError(_PUBLIC_UNAVAILABLE_MESSAGE) from None


@lru_cache(maxsize=1)
def _get_llm_gemini() -> ChatGoogleGenerativeAI:
    validate_llm_config(provider="gemini")
    settings = get_settings()
    # langchain-google-genai encaminha `max_retries` como total de tentativas
    # do SDK Google. Somamos a chamada inicial ao limite de retries da aplicação.
    return ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        callbacks=[ModelDiagnostics("google", settings.gemini_model)],
        temperature=0.3,
        top_p=0.95,
        api_key=settings.gemini_api_key,
        max_retries=settings.llm_max_retries + 1,
        timeout=settings.llm_timeout_seconds,
        max_output_tokens=settings.llm_max_output_tokens,
    )


@lru_cache(maxsize=1)
def _get_llm_groq_especialista() -> ChatGroq:
    validate_llm_config(provider="groq_specialist")
    settings = get_settings()
    return ChatGroq(
        model=settings.groq_specialist_model,
        callbacks=[ModelDiagnostics("groq", settings.groq_specialist_model)],
        temperature=0.3,
        api_key=settings.groq_api_key,
        max_retries=settings.llm_max_retries,
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
    return _FallbackLLM(
        _get_llm_gemini(),
        fallback,
        primary_provider="google",
        primary_model=settings.gemini_model,
        fallback_provider="groq",
        fallback_model=settings.groq_specialist_model if fallback is not None else None,
    )


@lru_cache(maxsize=1)
def _get_llm_rapido() -> ChatGroq:
    validate_llm_config(provider="fast")
    settings = get_settings()
    return ChatGroq(
        model=settings.groq_fast_model,
        callbacks=[ModelDiagnostics("groq", settings.groq_fast_model)],
        temperature=0.0,
        api_key=settings.groq_api_key,
        max_retries=settings.llm_max_retries,
        timeout=settings.llm_timeout_seconds,
        max_tokens=settings.llm_max_output_tokens,
    )


def clear_llm_cache() -> None:
    """Limpa modelos em cache após recarregar settings em testes ou desenvolvimento."""
    _get_llm_especialista.cache_clear()
    _get_llm_gemini.cache_clear()
    _get_llm_groq_especialista.cache_clear()
    _get_llm_rapido.cache_clear()
    # Remove instâncias cacheadas no __dict__ para que o próximo acesso construa
    # novos clientes com os settings/substitutos vigentes.
    module = sys.modules[__name__]
    exported_models = (
        "llm_gemini",
        "llm_groq_especialista",
        "llm_especialista",
        "llm_rapido",
    )
    for name in exported_models:
        module.__dict__.pop(name, None)


def __getattr__(name: str) -> Any:
    if name == "EMBEDDING_MODEL_NAME":
        return get_settings().gemini_embedding_model
    if name == "llm_gemini":
        return _get_llm_gemini()
    if name == "llm_groq_especialista":
        return _get_llm_groq_especialista()
    if name == "llm_especialista":
        return _get_llm_especialista()
    if name == "llm_rapido":
        try:
            return _get_llm_rapido()
        except ConfigurationError:
            return None
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None


def __dir__() -> list[str]:
    return sorted(__all__)
