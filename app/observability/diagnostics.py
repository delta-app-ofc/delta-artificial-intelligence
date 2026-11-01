"""Diagnósticos seguros e isolados por requisição, sem prompts ou credenciais."""
from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
import math
from pathlib import Path
import re
from threading import Lock
from time import perf_counter
import traceback
from typing import Any, Callable
from uuid import UUID, uuid4

from langchain_core.callbacks import BaseCallbackHandler

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_MAX_CAUSE_DEPTH = 5
_MAX_EVENTS = 200
_MAX_EVENT_TEXT = 120
_ALLOWED_EVENT_METADATA = {
    "method",
    "route",
    "status_code",
    "provider",
    "model",
    "error_id",
    "cause_type",
    "error_type",
    "cause_chain",
    "location",
    "fallback",
    "tool",
    "phase",
    "outcome",
    "revision_count",
}
# Contagens numéricas de uso do modelo não são tokens de autenticação.
_TOKEN_USAGE_FIELDS = {
    "input_tokens", "output_tokens", "total_tokens", "cached_tokens",
    "cached_input_tokens", "reasoning_tokens", "embedding_tokens", "jev_tokens",
}
_SECRET_KEY = re.compile(
    r"password|senha|secret|api.?key|authorization|pii.?map|token|credential|private.?key",
    re.I,
)
_PERSONAL_KEY = re.compile(
    r"^(?:e.?mail|cpf|phone|telefone|celular|mobile|full.?name|person.?name|nome.?completo|user.?name|username)$",
    re.I,
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|password|senha|secret|authorization|access[_-]?token|"
    r"refresh[_-]?token|token)\b(\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_BEARER_TOKEN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_URI = re.compile(
    r"""(?i)\b(?:postgres(?:ql)?|mongodb(?:\+srv)?|redis|https?)://[^\s"'<>]+"""
)
_active: ContextVar[Trace | None] = ContextVar("delta_diagnostics", default=None)
_component: ContextVar[str] = ContextVar("delta_component", default="request")
_fallback: ContextVar[bool] = ContextVar("delta_fallback", default=False)
_in_event_sink: ContextVar[bool] = ContextVar("delta_event_sink", default=False)
_event_sink_lock = Lock()
_event_sink: Callable[[dict], None] | None = None


def _redact_text(value: str) -> str:
    # IDs uuid4 dos eventos podem conter sequências que parecem CPF ou telefone.
    if len(value) == 32:
        try:
            if UUID(hex=value).version == 4:
                return value
        except ValueError:
            pass
    value = _URI.sub("[URI omitida]", value)
    value = _BEARER_TOKEN.sub("Bearer [omitido]", value)
    value = _SECRET_ASSIGNMENT.sub(r"\1\2[omitido]", value)
    # Importação local evita o ciclo com o guardrail de entrada, que usa diagnósticos.
    from app.guardrails.output import validate_output

    if not value.strip():
        return value
    checked = validate_output(value)
    return checked["response"] if checked["ok"] else "[conteúdo omitido]"


def public_data(value: Any) -> Any:
    """Redige dados pessoais e segredos sem converter objetos desconhecidos em texto."""
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            if not isinstance(key, str):
                continue
            safe_key = _redact_text(key)
            numeric_usage = (key.casefold() in _TOKEN_USAGE_FIELDS
                             and isinstance(item, int) and not isinstance(item, bool) and item >= 0)
            if numeric_usage:
                result[safe_key] = item
            elif _SECRET_KEY.search(key):
                result[safe_key] = "[omitido]"
            elif _PERSONAL_KEY.fullmatch(key.strip()):
                result[safe_key] = "[dado pessoal omitido]"
            else:
                result[safe_key] = public_data(item)
        return result
    if isinstance(value, (list, tuple)):
        return [public_data(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        if value.is_finite():
            return float(value)
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return "[valor omitido]"


def _safe_label(value: Any, default: str | None = None) -> str | None:
    if not isinstance(value, str):
        return default
    cleaned = public_data(value).strip()
    return cleaned[:_MAX_EVENT_TEXT] or default


def _safe_relative_file(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized) or ".." in normalized.split("/"):
        normalized = normalized.rsplit("/", 1)[-1]
    normalized = normalized.lstrip("./")
    return _safe_label(normalized, "unknown")


def _copy_containers(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _copy_containers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_containers(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_copy_containers(item) for item in value)
    return value


def _safe_metadata(metadata: Any) -> dict:
    if not isinstance(metadata, Mapping):
        return {}
    result = {}
    for key in _ALLOWED_EVENT_METADATA:
        if key not in metadata:
            continue
        value = metadata[key]
        if key in {"status_code", "revision_count"}:
            if isinstance(value, int) and not isinstance(value, bool):
                result[key] = value
        elif key == "fallback":
            if isinstance(value, bool):
                result[key] = value
        elif key == "cause_chain":
            if isinstance(value, (list, tuple)):
                result[key] = [
                    label for item in value[:_MAX_CAUSE_DEPTH]
                    if (label := _safe_label(item))
                ]
        elif key == "location":
            if isinstance(value, Mapping):
                safe_file = _safe_relative_file(value.get("file"))
                safe_function = _safe_label(value.get("function"))
                line = value.get("line")
                if safe_file and safe_function and isinstance(line, int) and not isinstance(line, bool) and line > 0:
                    result[key] = {
                        "file": safe_file,
                        "function": safe_function,
                        "line": line,
                    }
        elif isinstance(value, str):
            result[key] = _safe_label(value)
    return result


def _exception_name(error: BaseException) -> str:
    name = type(error).__name__
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,99}", name):
        return name
    return "Exception"


def _exception_chain(error: BaseException) -> list[BaseException]:
    chain = []
    seen = set()
    current: BaseException | None = error
    while isinstance(current, BaseException) and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        if len(chain) >= _MAX_CAUSE_DEPTH:
            break
        if current.__cause__ is not None:
            current = current.__cause__
        elif current.__context__ is not None:
            # A supressão afeta o traceback público; aqui só extraímos tipos e frames.
            current = current.__context__
        else:
            current = None
    return chain


def _safe_http_status(error_chain: list[BaseException]) -> int | None:
    for error in error_chain:
        try:
            status = getattr(error, "status_code", None)
            if not isinstance(status, int) or isinstance(status, bool):
                response = getattr(error, "response", None)
                status = getattr(response, "status_code", None) if response is not None else None
        except Exception:
            continue
        if isinstance(status, int) and not isinstance(status, bool) and 400 <= status <= 599:
            return status
    return None


def _safe_frame_location(error_chain: list[BaseException]) -> dict | None:
    for error in reversed(error_chain):
        frames = list(traceback.walk_tb(error.__traceback__)) if error.__traceback__ else []
        for frame, line in reversed(frames):
            filename = frame.f_code.co_filename
            try:
                path = Path(filename)
                if path.is_absolute():
                    resolved = path.resolve(strict=False)
                    try:
                        safe_file = resolved.relative_to(_PROJECT_ROOT).as_posix()
                    except ValueError:
                        safe_file = resolved.name
                else:
                    safe_file = path.as_posix()
            except (OSError, RuntimeError, ValueError):
                safe_file = Path(filename).name
            if not safe_file:
                safe_file = Path(filename).name
            return {
                "file": safe_file,
                "function": _safe_label(frame.f_code.co_name, "unknown"),
                "line": int(line),
            }
    return None


def safe_error(error: BaseException) -> str:
    """Retorna mensagem pública conhecida ou uma descrição genérica por tipo."""
    from app.config import ConfigurationError
    from app.tools.exceptions import DatabaseAccessError

    try:
        if isinstance(error, (ConfigurationError, DatabaseAccessError)):
            message = public_data(str(error))
            return message if isinstance(message, str) else "Falha de configuração ou acesso a dados."
        if type(error).__name__ in {"LLMUnavailableError", "LLMProviderError"}:
            message = public_data(str(error))
            return message if isinstance(message, str) else "O serviço de linguagem está indisponível."
    except Exception:
        pass
    return f"Falha de execução ({_exception_name(error)}). Os detalhes internos foram omitidos."


def set_event_sink(sink: Callable[[dict], None] | None) -> None:
    """Define um destino opcional para cópias sanitizadas dos eventos em memória."""
    if sink is not None and not callable(sink):
        raise TypeError("O destino de eventos precisa ser uma função ou None.")
    global _event_sink
    with _event_sink_lock:
        _event_sink = sink


def _notify_event_sink(row: dict) -> None:
    if _in_event_sink.get():
        return
    with _event_sink_lock:
        sink = _event_sink
    if sink is None:
        return
    token = _in_event_sink.set(True)
    try:
        sink(deepcopy(row))
    except Exception:
        # O destino de eventos não pode alterar a resposta da aplicação.
        pass
    finally:
        _in_event_sink.reset(token)


@dataclass
class Trace:
    mode: str
    user_id: int | str | None = None
    test_label: str | None = None
    client: str = "unknown"
    request_id: str = field(default_factory=lambda: uuid4().hex)
    started: float = field(default_factory=perf_counter)
    models: list = field(default_factory=list)
    tools: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    stages: list = field(default_factory=list)
    events: list = field(default_factory=list)
    dropped_event_count: int = 0
    selected_agents: list = field(default_factory=list)
    executed_agents: list = field(default_factory=list)
    skipped_agents: list = field(default_factory=list)
    routing: dict = field(default_factory=dict)
    lock: Lock = field(default_factory=Lock, repr=False)
    _seen_error_objects: dict[int, BaseException] = field(
        default_factory=dict, init=False, repr=False
    )
    _error_records: dict[int, dict] = field(default_factory=dict, init=False, repr=False)

    def event(
        self,
        event: str,
        *,
        component: str | None = None,
        operation: str | None = None,
        status: str | None = None,
        duration_ms: float | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict:
        """Guarda um evento sanitizado e chama, se configurado, o destino opcional."""
        duration = None
        if isinstance(duration_ms, (int, float)) and not isinstance(duration_ms, bool):
            if math.isfinite(duration_ms) and duration_ms >= 0:
                duration = round(float(duration_ms), 1)
        row = {
            "request_id": self.request_id,
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "event": _safe_label(event, "event"),
            "component": _safe_label(component if component is not None else current_component()),
            "operation": _safe_label(operation),
            "status": _safe_label(status),
            "duration_ms": duration,
            "metadata": _safe_metadata(metadata),
        }
        with self.lock:
            self.events.append(row)
            if len(self.events) > _MAX_EVENTS:
                self.events.pop(0)
                self.dropped_event_count += 1
        _notify_event_sink(row)
        return deepcopy(row)

    def error(
        self,
        stage: str,
        error: BaseException,
        *,
        operation: str | None = None,
        code: str | None = None,
        message: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict:
        """Registra tipos e localização; a exceção bruta não é serializada."""
        if not isinstance(error, BaseException):
            error = RuntimeError("Falha sem exceção válida.")
        chain = _exception_chain(error)
        error_id = uuid4().hex
        safe_code = _safe_label(code, _exception_name(error)) or _exception_name(error)
        safe_message = safe_error(error) if message is None else _safe_label(message)
        if safe_message is None:
            safe_message = safe_error(error)
        safe_causes = [_exception_name(item) for item in chain[1:]]
        cause_type = safe_causes[-1] if safe_causes else None
        safe_metadata = _safe_metadata(metadata)
        if "status_code" not in safe_metadata:
            status_code = _safe_http_status(chain)
            if status_code is not None:
                safe_metadata["status_code"] = status_code
        record = {
            "stage": _safe_label(stage, "request"),
            "code": safe_code,
            "message": safe_message,
            "error_id": error_id,
            "cause_type": cause_type,
            "cause_chain": safe_causes,
            "location": _safe_frame_location(chain),
            "operation": _safe_label(operation),
            "metadata": safe_metadata,
        }
        with self.lock:
            for item in chain:
                prior = self._seen_error_objects.get(id(item))
                if prior is item:
                    return self._error_records[id(item)]
            for item in chain:
                self._seen_error_objects[id(item)] = item
                self._error_records[id(item)] = record
            self.errors.append(record)

        current = current_component()
        event_component = stage if current == "request" else current
        event_metadata = dict(safe_metadata)
        event_metadata.update({"error_id": error_id, "error_type": _exception_name(error), "cause_chain": safe_causes, "location": record["location"]})
        if cause_type:
            event_metadata["cause_type"] = cause_type
        self.event(
            "operation.failed",
            component=event_component,
            operation=operation or stage,
            status="error",
            metadata=event_metadata,
        )
        return record

    def tool(
        self,
        agent: str,
        name: str,
        arguments: dict,
        output: Any,
        *,
        duration_ms: float | None = None,
        error_id: str | None = None,
    ) -> None:
        status = output.get("status", "success") if isinstance(output, dict) else "success"
        failed = status in {"error", "unavailable"}
        safe_name = _safe_label(name, "tool")
        matched_error = None
        new_failure = False
        with self.lock:
            self.tools.append({
                "agent": agent,
                "name": name,
                "input": arguments,
                "output": output,
                "status": status,
            })
            if failed:
                if error_id:
                    matched_error = next(
                        (item for item in self.errors if item.get("error_id") == error_id),
                        None,
                    )
                if matched_error is None:
                    new_failure = True
                    error_id = uuid4().hex
                    matched_error = {
                        "stage": agent,
                        "code": "tool_" + str(status),
                        "message": f"A ferramenta {safe_name} retornou {status}. Veja seus detalhes.",
                        "error_id": error_id,
                        "cause_type": None,
                        "cause_chain": [],
                        "location": None,
                        "operation": safe_name,
                        "metadata": {"tool": safe_name, "outcome": _safe_label(str(status))},
                    }
                    self.errors.append(matched_error)
                else:
                    error_id = matched_error.get("error_id")
        event_status = str(status) if status in {"error", "unavailable"} else "success"
        event_name = "operation.failed" if new_failure else "tool.end"
        event_metadata = {"tool": safe_name, "outcome": str(status)}
        if error_id:
            event_metadata["error_id"] = error_id
        if failed and matched_error and matched_error.get("cause_type"):
            event_metadata["cause_type"] = matched_error["cause_type"]
        self.event(
            event_name,
            component=agent,
            operation=safe_name,
            status=event_status,
            duration_ms=duration_ms,
            metadata=event_metadata,
        )

    def snapshot(self) -> dict:
        with self.lock:
            fields = (
                "request_id", "mode", "user_id", "test_label", "models", "tools",
                "errors", "warnings", "stages", "selected_agents", "executed_agents",
                "skipped_agents", "routing", "events", "dropped_event_count",
            )
            snapshot = {name: _copy_containers(getattr(self, name)) for name in fields}
        snapshot["duration_ms"] = round((perf_counter() - self.started) * 1000, 1)
        return public_data(snapshot)


def current_trace() -> Trace | None:
    return _active.get()


def current_component() -> str:
    return _component.get()


@contextmanager
def capture(trace: Trace):
    trace_token = _active.set(trace)
    component_token = _component.set("request")
    fallback_token = _fallback.set(False)
    try:
        yield trace
    finally:
        _fallback.reset(fallback_token)
        _component.reset(component_token)
        _active.reset(trace_token)


@contextmanager
def component(name: str):
    token = _component.set(name)
    start = perf_counter()
    status = "success"
    trace = current_trace()
    error_count = len(trace.errors) if trace else 0
    if trace:
        trace.event("component.start", component=name, operation=name, status="running")
    try:
        yield
    except Exception as error:
        status = "error"
        if trace:
            trace.error(name, error, operation=name)
        raise
    finally:
        duration_ms = round((perf_counter() - start) * 1000, 1)
        if trace:
            with trace.lock:
                if status == "success" and len(trace.errors) > error_count:
                    status = "partial"
                trace.stages.append({
                    "stage": name,
                    "status": status,
                    "duration_ms": duration_ms,
                })
            trace.event(
                "component.end",
                component=name,
                operation=name,
                status=status,
                duration_ms=duration_ms,
            )
        _component.reset(token)


@contextmanager
def fallback_call():
    token = _fallback.set(True)
    try:
        yield
    finally:
        _fallback.reset(token)


def _token_usage(response: Any) -> dict:
    """Lê as contagens de tokens da resposta; sem uso informado ou com formato inesperado, devolve vazio."""
    try:
        return _read_token_usage(response)
    except Exception:
        return {}


def _read_token_usage(response: Any) -> dict:
    try:
        usage = response.generations[0][0].message.usage_metadata
    except (AttributeError, IndexError, TypeError):
        usage = None
    if not isinstance(usage, Mapping):
        raw = (getattr(response, "llm_output", None) or {}).get("token_usage") or {}
        usage = {"input_tokens": raw.get("prompt_tokens"), "output_tokens": raw.get("completion_tokens")}
    result = {}
    for key in ("input_tokens", "output_tokens"):
        value = usage.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            result[key] = value
    details = usage.get("output_token_details")
    reasoning = details.get("reasoning") if isinstance(details, Mapping) else None
    if isinstance(reasoning, int) and not isinstance(reasoning, bool) and reasoning >= 0:
        result["reasoning_tokens"] = reasoning
    return result


class ModelDiagnostics(BaseCallbackHandler):
    """Registra provedor, modelo, resultado e falha segura das chamadas LangChain."""
    run_inline = True

    def __init__(self, provider: str, model: str):
        self.provider = provider
        self.model = model
        self.runs = {}
        self.lock = Lock()

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        try:
            trace = current_trace()
            if trace is None:
                return
            fallback = _fallback.get()
            row = {
                "component": current_component(),
                "provider": self.provider,
                "model": self.model,
                "status": "running",
                "fallback": fallback,
                "duration_ms": 0,
            }
            with trace.lock:
                trace.models.append(row)
            with self.lock:
                self.runs[run_id] = (trace, row, perf_counter())
            trace.event(
                "model.start",
                component=row["component"],
                operation="chat",
                status="running",
                metadata={
                    "provider": self.provider,
                    "model": self.model,
                    "fallback": fallback,
                },
            )
        except Exception:
            # Diagnósticos de callback não podem impedir a chamada ao modelo.
            return

    def _finish(self, run_id, status, error: BaseException | None = None, usage: Mapping | None = None):
        with self.lock:
            run = self.runs.pop(run_id, None)
        if not run:
            return
        trace, row, start = run
        duration_ms = round((perf_counter() - start) * 1000, 1)
        with trace.lock:
            row.update(status=status, duration_ms=duration_ms)
            if usage:
                row.update(usage)
        if error is not None:
            try:
                record = trace.error(
                    row["component"],
                    error,
                    operation="chat",
                    metadata={"provider": row["provider"], "model": row["model"]},
                )
                with trace.lock:
                    row["error_id"] = record.get("error_id")
                    row["cause_type"] = record.get("cause_type")
            except Exception:
                pass
        trace.event(
            "model.end",
            component=row["component"],
            operation="chat",
            status=status,
            duration_ms=duration_ms,
            metadata={
                "provider": row["provider"],
                "model": row["model"],
                "fallback": row["fallback"],
                "outcome": status,
                **({"error_id": row["error_id"]} if row.get("error_id") else {}),
                **({"cause_type": row["cause_type"]} if row.get("cause_type") else {}),
            },
        )

    def on_llm_end(self, response, *, run_id, **kwargs):
        try:
            self._finish(run_id, "success", usage=_token_usage(response))
        except Exception:
            return

    def on_llm_error(self, error, *, run_id, **kwargs):
        try:
            if not isinstance(error, BaseException):
                error = RuntimeError("Falha de callback do modelo.")
            self._finish(run_id, "error", error)
        except Exception:
            # Não propaga erros de instrumentação para o fluxo de execução.
            return


def _count_embedding_tokens(model: str, texts) -> int | None:
    """Conta os tokens do texto enviado com o count_tokens oficial do Google.

    A resposta de embed_content não traz o uso, então a contagem é uma chamada à parte.
    Se falhar, devolve None: o custo é marcado como sem contagem em vez de estimado.
    """
    if not texts:
        return None
    try:
        from google import genai

        from app.config import get_settings

        client = genai.Client(api_key=get_settings().gemini_api_key)
        return int(client.models.count_tokens(model=model, contents=list(texts)).total_tokens)
    except Exception:
        return None


@contextmanager
def embedding_call(model: str, texts=None):
    """Registra embeddings, que não passam pelos callbacks de modelos de chat."""
    trace = current_trace()
    component_name = current_component()
    row = {
        "component": component_name,
        "provider": "google",
        "model": model,
        "status": "running",
        "fallback": False,
        "duration_ms": 0,
        "kind": "embedding",
    }
    start = perf_counter()
    if trace:
        with trace.lock:
            trace.models.append(row)
        trace.event(
            "model.start",
            component=component_name,
            operation="embedding",
            status="running",
            metadata={"provider": "google", "model": model},
        )
    ended = None
    try:
        yield
        ended = perf_counter()
        row["status"] = "success"
        row["input_tokens"] = _count_embedding_tokens(model, texts)
    except Exception as error:
        row["status"] = "error"
        if trace:
            try:
                record = trace.error(
                    component_name,
                    error,
                    operation="embedding",
                    metadata={"provider": "google", "model": model},
                )
                row["error_id"] = record.get("error_id")
                row["cause_type"] = record.get("cause_type")
            except Exception:
                pass
        raise
    finally:
        duration_ms = round(((ended or perf_counter()) - start) * 1000, 1)
        row["duration_ms"] = duration_ms
        if trace:
            trace.event(
                "model.end",
                component=component_name,
                operation="embedding",
                status=row["status"],
                duration_ms=duration_ms,
                metadata={
                    "provider": "google",
                    "model": model,
                    "outcome": row["status"],
                    **({"error_id": row["error_id"]} if row.get("error_id") else {}),
                    **({"cause_type": row["cause_type"]} if row.get("cause_type") else {}),
                },
            )
