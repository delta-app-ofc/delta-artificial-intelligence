"""Contrato HTTP/MCP e falhas, com transporte real em memória e HTTP controlado."""

import asyncio
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from mcp import Client
from pydantic import ValidationError
import pytest

from app.config import ConfigurationError, load_settings, validate_mcp_config
from app.integrations.mcp import client as mcp_client
from app.integrations.mcp import server as mcp_server
from app.integrations.mcp.sources import (
    ExternalDocument, ExternalSourceError, MAX_RESPONSE_BYTES, SOURCES, read_source,
)

SOURCE_ID = next(iter(SOURCES))


def make_snapshot(text=None):
    source = SOURCES[SOURCE_ID]
    text = text or ("Use água com cuidado. Feche o chuveiro enquanto se ensaboa.\n" * 6).strip()
    return ExternalDocument(
        source_id=source.id, title=source.title, url=source.url, topic=source.topic,
        published_at=source.published_at, collected_at="2026-11-01T03:00:00+00:00",
        revision=hashlib.sha256(text.encode("utf-8")).hexdigest(), text=text,
    )


def test_extracts_article_only_and_preserves_provenance():
    text = make_snapshot().text
    html = f'<nav>NÃO INDEXAR MENU</nav><div class="js-Materia"><p>{text}</p>'
    html += '<script>NÃO INDEXAR SCRIPT</script><style>CSS</style></div><footer>RODAPÉ</footer>'
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, text=html, headers={"content-type": "text/html; charset=utf-8"})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        snapshot = read_source(SOURCE_ID, client=client)
    assert snapshot.text == text
    assert snapshot.url == SOURCES[SOURCE_ID].url
    assert snapshot.revision == make_snapshot().revision
    assert len(requests) == 1 and requests[0].method == "GET"
    assert not requests[0].url.query and not requests[0].content
    assert "authorization" not in requests[0].headers


@pytest.mark.parametrize("response", [
    httpx.Response(302, headers={"location": "http://127.0.0.1/private"}),
    httpx.Response(401), httpx.Response(429), httpx.Response(503),
    httpx.Response(200, text="{}", headers={"content-type": "application/json"}),
    httpx.Response(200, text="<html>Challenge de proteção</html>", headers={"content-type": "text/html"}),
    httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1), headers={"content-type": "text/html"}),
    httpx.Response(200, text='<div class="js-Materia">curto</div>', headers={"content-type": "text/html"}),
])
def test_http_failures_do_not_become_empty_or_partial_documents(response):
    with httpx.Client(transport=httpx.MockTransport(lambda request: response)) as client:
        with pytest.raises(ExternalSourceError):
            read_source(SOURCE_ID, client=client)


def test_timeout_and_unknown_source_never_expose_raw_error():
    def fail(request):
        raise httpx.ReadTimeout("TOKEN_SECRETO", request=request)
    with httpx.Client(transport=httpx.MockTransport(fail)) as client:
        with pytest.raises(ExternalSourceError, match="Não foi possível") as error:
            read_source(SOURCE_ID, client=client)
        assert "TOKEN_SECRETO" not in str(error.value)
        with pytest.raises(ExternalSourceError, match="desconhecida"):
            read_source("http://127.0.0.1/private", client=client)


@pytest.mark.parametrize("change", [
    {"source_id": "unknown"}, {"url": "https://evil.example/doc"}, {"revision": "wrong"},
    {"collected_at": "2026-11-01T00:00:00"}, {"text": "vazio"}, {"topic": "weather"},
])
def test_client_contract_rejects_changed_provenance(change):
    with pytest.raises(ValidationError):
        ExternalDocument.model_validate({**make_snapshot().model_dump(), **change})


def test_mcp_protocol_lists_and_calls_tools_with_success_and_unavailability(monkeypatch):
    async def scenario():
        async with Client(mcp_server.server) as client:
            tools = await client.list_tools()
            listing = await client.call_tool("list_knowledge_sources", {})
            result = await client.call_tool("read_knowledge_source", {"source_id": SOURCE_ID})
            monkeypatch.setattr(mcp_server, "read_source", lambda source_id: (_ for _ in ()).throw(ExternalSourceError()))
            failed = await client.call_tool("read_knowledge_source", {"source_id": SOURCE_ID})
        assert {tool.name for tool in tools.tools} == {"list_knowledge_sources", "read_knowledge_source"}
        assert listing.structured_content["sources"][0]["id"] == SOURCE_ID
        assert not result.is_error
        assert result.structured_content["document"] == make_snapshot().model_dump()
        assert failed.structured_content["status"] == "unavailable"
        assert "document" not in failed.structured_content
    monkeypatch.setattr(mcp_server, "read_source", lambda source_id: make_snapshot())
    asyncio.run(scenario())


def test_cache_expires_and_failure_is_not_cached(monkeypatch):
    settings = load_settings({"APP_ENV": "test", "MCP_EXTERNAL_ENABLED": "true", "MCP_CACHE_TTL_SECONDS": "60"})
    monkeypatch.setattr(mcp_client, "get_settings", lambda: settings)
    clock = [100.0]
    monkeypatch.setattr(mcp_client, "monotonic", lambda: clock[0])
    call = AsyncMock(return_value=make_snapshot())
    monkeypatch.setattr(mcp_client, "call_source", call)
    mcp_client.clear_source_cache()
    assert mcp_client.fetch_source(SOURCE_ID) == mcp_client.fetch_source(SOURCE_ID)
    assert call.await_count == 1
    clock[0] += 61
    call.side_effect = ExternalSourceError("falhou")
    with pytest.raises(ExternalSourceError):
        mcp_client.fetch_source(SOURCE_ID)
    call.side_effect = None
    assert mcp_client.fetch_source(SOURCE_ID) == make_snapshot()
    assert call.await_count == 3
    mcp_client.clear_source_cache()


@pytest.mark.parametrize("values", [
    {"MCP_EXTERNAL_ENABLED": "talvez"}, {"MCP_EXTERNAL_ENABLED": ""},
    {"MCP_TIMEOUT_SECONDS": "NaN"}, {"MCP_TIMEOUT_SECONDS": "0"},
    {"MCP_TIMEOUT_SECONDS": "121"}, {"MCP_CACHE_TTL_SECONDS": "-1"},
])
def test_lazy_settings_validate_only_mcp(values):
    with pytest.raises(ConfigurationError):
        validate_mcp_config(settings=load_settings({"APP_ENV": "test", **values}))
    validate_mcp_config(settings=load_settings({"APP_ENV": "test"}))


def test_stdio_uses_project_module_and_does_not_pass_backend_secrets(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "SEGREDO_BACKEND")
    params = mcp_client.server_parameters()
    assert params.args == ["-m", "app.integrations.mcp.server"]
    assert params.env == {"PYTHONUTF8": "1"}


def test_client_total_timeout_is_safe(monkeypatch):
    class SlowClient:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self):
            await asyncio.sleep(1)
        async def __aexit__(self, *args): pass
    monkeypatch.setattr(mcp_client, "Client", SlowClient)
    with pytest.raises(ExternalSourceError):
        asyncio.run(mcp_client.call_source(SOURCE_ID, 0.01))


@pytest.mark.parametrize("payload,is_error", [
    (None, False), ({"status": "unavailable"}, False),
    ({"status": "ok", "document": {}}, False),
    ({"status": "ok", "document": make_snapshot().model_dump()}, True),
])
def test_client_rejects_invalid_or_failed_mcp_results(monkeypatch, payload, is_error):
    class ControlledClient:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def call_tool(self, name, arguments):
            assert name == "read_knowledge_source" and arguments == {"source_id": SOURCE_ID}
            return SimpleNamespace(structured_content=payload, is_error=is_error)
    monkeypatch.setattr(mcp_client, "Client", ControlledClient)
    with pytest.raises(ExternalSourceError, match="via MCP"):
        asyncio.run(mcp_client.call_source(SOURCE_ID, 1))
