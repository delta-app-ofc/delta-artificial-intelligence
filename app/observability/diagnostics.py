"""Diagnósticos isolados por requisição, sem armazenar prompts ou credenciais."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import re
from threading import Lock
from time import perf_counter
from typing import Any
from uuid import uuid4

from langchain_core.callbacks import BaseCallbackHandler

_active: ContextVar[Trace | None] = ContextVar("delta_diagnostics", default=None)
_component: ContextVar[str] = ContextVar("delta_component", default="request")
_fallback: ContextVar[bool] = ContextVar("delta_fallback", default=False)
_SECRET_KEY = re.compile(r"password|senha|secret|api.?key|authorization|pii_map|token", re.I)


def public_data(value: Any) -> Any:
    """Remove credenciais e URIs antes de entregar diagnósticos ao navegador."""
    if isinstance(value, dict):
        return {str(k): "[omitido]" if _SECRET_KEY.search(str(k)) else public_data(v)
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [public_data(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"""(?:postgres(?:ql)?|mongodb(?:\+srv)?|https?)://[^\s"']+""",
                       "[URI omitida]", value)
        return re.sub(r"(?i)(api[_-]?key|password|senha|secret|authorization)\s*[:=]\s*\S+",
                      r"\1=[omitido]", value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


def safe_error(error: Exception) -> str:
    """Só tipos com mensagens públicas controladas podem revelar sua mensagem."""
    from app.config import ConfigurationError
    from app.tools.exceptions import DatabaseAccessError
    if isinstance(error, (ConfigurationError, DatabaseAccessError)):
        return public_data(str(error))
    if type(error).__name__ in {"LLMUnavailableError", "LLMProviderError"}:
        return public_data(str(error))
    return f"Falha de execução ({type(error).__name__}). Os detalhes internos foram omitidos."


@dataclass
class Trace:
    mode: str
    user_id: int = 12345679
    test_label: str = "teste_agentes_25_10"
    request_id: str = field(default_factory=lambda: uuid4().hex)
    started: float = field(default_factory=perf_counter)
    models: list = field(default_factory=list)
    tools: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    stages: list = field(default_factory=list)
    selected_agents: list = field(default_factory=list)
    executed_agents: list = field(default_factory=list)
    skipped_agents: list = field(default_factory=list)
    routing: dict = field(default_factory=dict)
    lock: Lock = field(default_factory=Lock, repr=False)

    def error(self, stage: str, error: Exception) -> None:
        with self.lock:
            self.errors.append({"stage": stage, "code": type(error).__name__, "message": safe_error(error)})

    def tool(self, agent: str, name: str, arguments: dict, output: Any) -> None:
        status = output.get("status", "success") if isinstance(output, dict) else "success"
        with self.lock:
            self.tools.append({"agent": agent, "name": name, "input": arguments,
                               "output": output, "status": status})
            if status in {"error", "unavailable"}:
                self.errors.append({"stage": agent, "code": "tool_" + status,
                                    "message": f"A ferramenta {name} retornou {status}. Veja seus detalhes."})

    def snapshot(self) -> dict:
        fields = ("request_id", "mode", "user_id", "test_label", "models", "tools", "errors",
                  "warnings", "stages", "selected_agents", "executed_agents", "skipped_agents", "routing")
        return public_data({name: getattr(self, name) for name in fields}
                           | {"duration_ms": round((perf_counter() - self.started) * 1000, 1)})


def current_trace() -> Trace | None:
    return _active.get()


def current_component() -> str:
    return _component.get()


@contextmanager
def capture(trace: Trace):
    token = _active.set(trace)
    try:
        yield trace
    finally:
        _active.reset(token)


@contextmanager
def component(name: str):
    token = _component.set(name)
    start = perf_counter()
    status = "success"
    trace_at_start = current_trace()
    error_count = len(trace_at_start.errors) if trace_at_start else 0
    try:
        yield
    except Exception as error:
        status = "error"
        if trace := current_trace():
            trace.error(name, error)
        raise
    finally:
        if trace := current_trace():
            if status == "success" and len(trace.errors) > error_count:
                status = "partial"
            with trace.lock:
                trace.stages.append({"stage": name, "status": status,
                                     "duration_ms": round((perf_counter() - start) * 1000, 1)})
        _component.reset(token)


@contextmanager
def fallback_call():
    token = _fallback.set(True)
    try:
        yield
    finally:
        _fallback.reset(token)


class ModelDiagnostics(BaseCallbackHandler):
    """Registra chamadas reais do LangChain, inclusive as executadas pelo RAG."""
    run_inline = True

    def __init__(self, provider: str, model: str):
        self.provider = provider
        self.model = model
        self.runs = {}
        self.lock = Lock()

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        trace = current_trace()
        if trace is None:
            return
        row = {"component": _component.get(), "provider": self.provider, "model": self.model,
               "status": "running", "fallback": _fallback.get(), "duration_ms": 0}
        with trace.lock:
            trace.models.append(row)
        with self.lock:
            self.runs[run_id] = (trace, row, perf_counter())

    def _finish(self, run_id, status):
        with self.lock:
            run = self.runs.pop(run_id, None)
        if run:
            trace, row, start = run
            with trace.lock:
                row.update(status=status, duration_ms=round((perf_counter() - start) * 1000, 1))

    def on_llm_end(self, response, *, run_id, **kwargs):
        self._finish(run_id, "success")

    def on_llm_error(self, error, *, run_id, **kwargs):
        self._finish(run_id, "error")


@contextmanager
def embedding_call(model: str):
    """Embeddings não passam pelos callbacks de modelos de chat."""
    trace = current_trace()
    row = {"component": _component.get(), "provider": "google", "model": model,
           "status": "running", "fallback": False, "duration_ms": 0, "kind": "embedding"}
    start = perf_counter()
    if trace:
        with trace.lock:
            trace.models.append(row)
    try:
        yield
        row["status"] = "success"
    except Exception as error:
        row["status"] = "error"
        if trace:
            trace.error(_component.get(), error)
        raise
    finally:
        row["duration_ms"] = round((perf_counter() - start) * 1000, 1)
