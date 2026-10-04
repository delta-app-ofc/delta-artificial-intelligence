"""Testes da configuração lazy e do fallback de provedores sem chamadas reais."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from google.genai.errors import APIError as GoogleAPIError
from groq import APITimeoutError as GroqAPITimeoutError
from groq import APIStatusError as GroqAPIStatusError
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool

from app.agents._runtime import run_agent
from app.config import load_settings, validate_llm_config
from app.services import llms
from tests.fakes import ai_final, ai_tool_call


class ProviderSpy:
    """Modelo falso que guarda schemas e mensagens recebidas por cada provedor."""

    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.bound_tools: list[tuple[Any, dict[str, Any]]] = []
        self.inputs: list[Any] = []
        self.input_snapshots: list[list[Any]] = []

    def bind_tools(self, tools: Any, **kwargs: Any) -> ProviderSpy:
        self.bound_tools.append((tools, kwargs))
        return self

    def invoke(
        self,
        messages: Any,
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        self.inputs.append(messages)
        if isinstance(messages, list):
            self.input_snapshots.append(list(messages))
        if not self.responses:
            raise AssertionError("o roteiro do modelo falso terminou")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def _settings(*, fallback_enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        gemini_api_key="synthetic-gemini-key",
        groq_api_key="synthetic-groq-key",
        gemini_model="gemini-test-model",
        groq_specialist_model="groq-specialist-test-model",
        groq_fast_model="groq-fast-test-model",
        llm_fallback_enabled=fallback_enabled,
        llm_timeout_seconds=12.5,
        llm_max_retries=2,
        llm_max_output_tokens=3456,
    )


@pytest.fixture(autouse=True)
def clear_provider_caches():
    llms.clear_llm_cache()
    yield
    llms.clear_llm_cache()


def _groq_timeout() -> GroqAPITimeoutError:
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    return GroqAPITimeoutError(request=request)


def _google_error(status_code: int, detail: str = "synthetic-private-detail") -> GoogleAPIError:
    return GoogleAPIError(status_code, {"error": {"message": detail}})


def _groq_error(status_code: int, detail: str = "synthetic-private-detail") -> GroqAPIStatusError:
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(status_code, request=request)
    return GroqAPIStatusError(detail, response=response, body={"message": detail})


def _provider_error(provider: str, status_code: int) -> Exception:
    if provider == "google":
        return _google_error(status_code)
    return _groq_error(status_code)


def test_import_without_keys_does_not_construct_provider_clients(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    calls: list[str] = []

    def fail_if_constructed(*args, **kwargs):
        calls.append("created")
        raise AssertionError("a importação não deve construir clientes")

    monkeypatch.setattr(llms.ChatGoogleGenerativeAI, "__init__", fail_if_constructed)
    monkeypatch.setattr(llms.ChatGroq, "__init__", fail_if_constructed)

    importlib.reload(llms)

    assert calls == []
    assert llms.EMBEDDING_MODEL_NAME == "gemini-embedding-2-preview"


def test_builder_key_error_is_not_misreported_as_unknown_attribute(monkeypatch):
    def broken_builder():
        raise KeyError("internal builder bug")

    monkeypatch.setitem(llms._LAZY, "llm_gemini", broken_builder)

    with pytest.raises(KeyError, match="internal builder bug"):
        _ = llms.llm_gemini


def test_provider_models_receive_settings_and_finite_parameters(monkeypatch):
    settings = _settings()
    created: dict[str, list[tuple[dict[str, Any], ProviderSpy]]] = {
        "gemini": [],
        "groq": [],
    }
    validated: list[str] = []

    def make_factory(name: str):
        def factory(**kwargs: Any) -> ProviderSpy:
            model = ProviderSpy([])
            created[name].append((kwargs, model))
            return model

        return factory

    monkeypatch.setattr(llms, "get_settings", lambda: settings)
    monkeypatch.setattr(
        llms,
        "validate_llm_config",
        lambda *, provider: validated.append(provider),
    )
    monkeypatch.setattr(llms, "ChatGoogleGenerativeAI", make_factory("gemini"))
    monkeypatch.setattr(llms, "ChatGroq", make_factory("groq"))

    specialist = llms.llm_especialista
    fast = llms.llm_rapido

    assert specialist._primary is created["gemini"][0][1]
    assert specialist._fallback is created["groq"][0][1]
    assert created["gemini"][0][0] == {
        "model": "gemini-test-model",
        "temperature": 0.3,
        "top_p": 0.95,
        "api_key": "synthetic-gemini-key",
        "max_retries": 3,
        "timeout": 12.5,
        "max_output_tokens": 3456,
    }
    assert created["groq"][0][0] == {
        "model": "groq-specialist-test-model",
        "temperature": 0.3,
        "api_key": "synthetic-groq-key",
        "max_retries": 2,
        "timeout": 12.5,
        "max_tokens": 3456,
    }
    # O modelo rápido é outro cliente Groq, com o identificador e temperatura próprios.
    assert fast is created["groq"][1][1]
    assert created["groq"][1][0] == {
        "model": "groq-fast-test-model",
        "temperature": 0.0,
        "api_key": "synthetic-groq-key",
        "max_retries": 2,
        "timeout": 12.5,
        "max_tokens": 3456,
    }
    assert set(validated) >= {"specialist", "gemini", "groq_specialist", "fast"}
