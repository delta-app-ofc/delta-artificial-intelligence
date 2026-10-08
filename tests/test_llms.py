"""Testes da configuração lazy e do fallback de provedores sem chamadas reais."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from google.genai.errors import ClientError as GoogleClientError
from google.genai.errors import ServerError as GoogleServerError
from groq import APITimeoutError as GroqAPITimeoutError
from groq import APIStatusError as GroqAPIStatusError
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langchain_google_genai.chat_models import (
    ChatGoogleGenerativeAIError,
    _handle_client_error,
)

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


def _google_error(
    status_code: int, detail: str = "synthetic-private-detail"
) -> Exception:
    response_json = {"error": {"message": detail}}
    if 400 <= status_code < 500:
        cause = GoogleClientError(status_code, response_json)
        try:
            _handle_client_error(cause, {"model": "synthetic-model"})
        except ChatGoogleGenerativeAIError as wrapper:
            return wrapper
        raise AssertionError("_handle_client_error deveria lançar o wrapper")
    return GoogleServerError(status_code, response_json)


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


def test_primary_success_does_not_invoke_fallback():
    primary = ProviderSpy([ai_final("resposta principal")])
    fallback = ProviderSpy([ai_final("resposta alternativa")])
    tools = [{"type": "function", "function": {"name": "lookup"}}]
    messages = [HumanMessage(content="consulta")]

    response = llms._FallbackLLM(primary, fallback).bind_tools(tools).invoke(messages)

    assert response.content == "resposta principal"
    assert len(primary.inputs) == 1
    assert fallback.inputs == []
    assert primary.bound_tools[0][0] is tools
    assert fallback.bound_tools[0][0] is tools


def test_transient_primary_error_uses_fallback_with_same_tools_and_messages():
    primary = ProviderSpy([_groq_timeout()])
    fallback = ProviderSpy([ai_final("resposta alternativa")])
    tools = [{"type": "function", "function": {"name": "lookup"}}]
    messages = [HumanMessage(content="consulta")]

    response = llms._FallbackLLM(primary, fallback).bind_tools(tools).invoke(messages)

    assert response.content == "resposta alternativa"
    assert primary.inputs[0] is messages
    assert fallback.inputs[0] is messages
    assert primary.bound_tools[0][0] is tools
    assert fallback.bound_tools[0][0] is tools


def test_fallback_tool_call_runs_once_and_receives_tool_message_on_next_turn():
    tool_effects: list[int] = []

    def lookup(value: int) -> dict[str, int]:
        tool_effects.append(value)
        return {"value": value + 1}

    lookup_tool = StructuredTool.from_function(
        lookup,
        name="lookup",
        description="Consulta um valor de teste.",
    )
    primary = ProviderSpy([_groq_timeout(), _groq_timeout()])
    fallback = ProviderSpy(
        [
            ai_tool_call("lookup", {"value": 6}, "lookup-call"),
            ai_final("A consulta retornou 7."),
        ]
    )

    result = run_agent(
        llm=llms._FallbackLLM(primary, fallback),
        system_prompt="Responda usando a ferramenta quando necessário.",
        tools=[lookup_tool],
        question="Consulte o valor 6.",
    )

    assert result.response == "A consulta retornou 7."
    assert [call.name for call in result.tool_calls] == ["lookup"]
    assert tool_effects == [6]
    assert len(fallback.bound_tools) == 1
    assert fallback.bound_tools[0][0] == [lookup_tool]
    assert len(fallback.input_snapshots) == 2
    second_turn = fallback.input_snapshots[1]
    assert any(isinstance(message, ToolMessage) for message in second_turn)
    assert any('"value": 7' in message.content for message in second_turn if isinstance(message, ToolMessage))


@pytest.mark.parametrize("provider", ["google", "groq"])
@pytest.mark.parametrize("status_code", [400, 401, 403])
def test_non_transient_provider_errors_are_safe_and_do_not_fallback(
    provider: str, status_code: int
):
    primary = ProviderSpy([_provider_error(provider, status_code)])
    fallback = ProviderSpy([ai_final("não deve ser chamada")])
    model = llms._FallbackLLM(primary, fallback).bind_tools([])

    with pytest.raises(llms.LLMProviderError) as error:
        model.invoke([HumanMessage(content="consulta")])

    assert f"HTTP {status_code}" in str(error.value)
    assert "synthetic-private-detail" not in str(error.value)
    assert fallback.inputs == []


def test_google_wrapper_without_recognized_cause_propagates():
    wrapper = ChatGoogleGenerativeAIError("synthetic wrapper without cause")
    primary = ProviderSpy([wrapper])
    fallback = ProviderSpy([ai_final("não deve ser chamada")])
    model = llms._FallbackLLM(primary, fallback).bind_tools([])

    with pytest.raises(ChatGoogleGenerativeAIError) as error:
        model.invoke([HumanMessage(content="consulta")])

    assert error.value is wrapper
    assert fallback.inputs == []


@pytest.mark.parametrize("provider", ["google", "groq"])
@pytest.mark.parametrize("status_code", [408, 429, 500, 503])
def test_transient_provider_status_uses_fallback(provider: str, status_code: int):
    primary = ProviderSpy([_provider_error(provider, status_code)])
    fallback = ProviderSpy([ai_final("resposta alternativa")])
    messages = [HumanMessage(content="consulta")]

    response = llms._FallbackLLM(primary, fallback).bind_tools([]).invoke(messages)

    assert response.content == "resposta alternativa"
    assert primary.inputs == [messages]
    assert fallback.inputs == [messages]


@pytest.mark.parametrize(
    "transport_error",
    [
        httpx.TimeoutException("synthetic timeout"),
        httpx.ConnectError(
            "synthetic connection",
            request=httpx.Request("POST", "https://generativelanguage.googleapis.com"),
        ),
        GroqAPITimeoutError(
            request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
        ),
    ],
    ids=["httpx-timeout", "httpx-connect", "groq-timeout"],
)
def test_transport_errors_use_fallback(transport_error: Exception):
    primary = ProviderSpy([transport_error])
    fallback = ProviderSpy([ai_final("resposta alternativa")])

    response = llms._FallbackLLM(primary, fallback).bind_tools([]).invoke(
        [HumanMessage(content="consulta")]
    )

    assert response.content == "resposta alternativa"
    assert len(primary.inputs) == 1
    assert len(fallback.inputs) == 1


@pytest.mark.parametrize("programming_error", [TypeError("tipo"), ValueError("valor")])
def test_programming_errors_are_not_masked_or_retried(programming_error: Exception):
    primary = ProviderSpy([programming_error])
    fallback = ProviderSpy([ai_final("não deve ser chamada")])
    model = llms._FallbackLLM(primary, fallback)

    with pytest.raises(type(programming_error), match=str(programming_error)):
        model.invoke([HumanMessage(content="consulta")])

    assert fallback.inputs == []


def test_both_transient_providers_fail_with_safe_error():
    primary = ProviderSpy([_google_error(503)])
    fallback = ProviderSpy([_groq_error(429)])
    model = llms._FallbackLLM(primary, fallback).bind_tools([])

    with pytest.raises(llms.LLMUnavailableError) as error:
        model.invoke([HumanMessage(content="consulta")])

    assert str(error.value) == "O serviço de linguagem está indisponível no momento."
    assert "synthetic-private-detail" not in str(error.value)
    assert len(primary.inputs) == 1
    assert len(fallback.inputs) == 1


def test_disabled_fallback_does_not_require_or_construct_groq(monkeypatch):
    settings = load_settings(
        environ={
            "APP_ENV": "test",
            "GEMINI_API_KEY": "synthetic-gemini-key",
            "LLM_FALLBACK_ENABLED": "false",
        }
    )
    assert settings.groq_api_key is None
    primary = ProviderSpy([ai_final("resposta Gemini")])
    constructed: list[str] = []
    validated: list[str] = []

    def validate_selected_provider(*, provider: str) -> None:
        validated.append(provider)
        validate_llm_config(provider, settings=settings)

    monkeypatch.setattr(llms, "get_settings", lambda: settings)
    monkeypatch.setattr(
        llms,
        "validate_llm_config",
        validate_selected_provider,
    )
    monkeypatch.setattr(
        llms,
        "ChatGoogleGenerativeAI",
        lambda **kwargs: (constructed.append("gemini"), primary)[1],
    )
    monkeypatch.setattr(
        llms,
        "ChatGroq",
        lambda **kwargs: (constructed.append("groq"), ProviderSpy([]))[1],
    )

    specialist = llms.llm_especialista
    response = specialist.bind_tools([]).invoke([HumanMessage(content="consulta")])

    assert response.content == "resposta Gemini"
    assert constructed == ["gemini"]
    assert set(validated) >= {"specialist", "gemini"}
    assert "groq_specialist" not in validated


def test_invalid_configuration_fails_before_constructing_models(monkeypatch):
    settings = load_settings(environ={"APP_ENV": "test"})
    constructed: list[str] = []

    def validate(*, provider: str) -> None:
        validate_llm_config(provider, settings=settings)

    monkeypatch.setattr(llms, "get_settings", lambda: settings)
    monkeypatch.setattr(llms, "validate_llm_config", validate)
    monkeypatch.setattr(
        llms,
        "ChatGoogleGenerativeAI",
        lambda **kwargs: constructed.append("gemini"),
    )
    monkeypatch.setattr(
        llms,
        "ChatGroq",
        lambda **kwargs: constructed.append("groq"),
    )

    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        _ = llms.llm_especialista

    assert constructed == []
