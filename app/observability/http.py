"""Mantém um contexto de rastreamento em cada requisição HTTP da aplicação."""
from __future__ import annotations

from time import perf_counter

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.observability.diagnostics import Trace, capture
from app.observability.metrics import client_from_scope, record_request


class RequestTracingMiddleware:
    """Entrega o mesmo identificador na execução e na resposta, inclusive em erros."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # O servidor gera o ID; não copia identificadores arbitrários do cliente.
        trace = Trace(mode="http", user_id=None, test_label=None)
        trace.client = client_from_scope(scope)
        scope.setdefault("state", {})["request_id"] = trace.request_id
        status_code = 500
        response_started = False
        failed = False
        started = perf_counter()

        async def send_traced(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                headers = [(key, value) for key, value in message.get("headers", [])
                           if key.lower() != b"x-request-id"]
                headers.append((b"x-request-id", trace.request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        with capture(trace):
            trace.event("request.started", component="http", operation=scope["method"],
                        status="running", metadata={"method": scope["method"]})
            try:
                await self.app(scope, receive, send_traced)
            except Exception as error:
                failed = True
                trace.error("http", error, operation=scope["method"])
                if response_started:
                    # Cabeçalhos enviados impedem substituir a resposta com segurança.
                    raise
                response = JSONResponse(
                    {"detail": "Não foi possível concluir a requisição.",
                     "request_id": trace.request_id}, status_code=500,
                )
                await response(scope, receive, send_traced)
            finally:
                route = getattr(scope.get("route"), "path", None)
                rejected = any(event.get("event") == "guardrail.rejected" for event in trace.events)
                outcome = ("error" if failed or status_code >= 500 else
                           "rejected" if status_code >= 400 or rejected else
                           "partial" if trace.errors else "success")
                total_ms = round((perf_counter() - started) * 1000, 1)
                trace.event(
                    "request.finished", component="http", operation=scope["method"],
                    status=outcome, duration_ms=total_ms,
                    metadata={"method": scope["method"], "route": route,
                              "status_code": status_code},
                )
                record_request(trace, outcome, total_ms)
