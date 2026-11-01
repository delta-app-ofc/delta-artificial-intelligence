"""Garante trabalho evitado e limites de falha; não simula latência de provedores reais."""

import asyncio
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timedelta, timezone
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import ConfigurationError, load_settings, validate_mcp_config
from app.integrations.mcp import client as mcp_client
from app.integrations.mcp.sources import SOURCES
from app.observability import diagnostics, embedding_usage, metrics
from app.observability.diagnostics import Trace, capture, public_data
from app.services import external_knowledge as service
from app.services import rag
from app.tools import external_knowledge as tool_module
from test_external_rag import rag_backend, prepare_sources, thematic_snapshot
from test_mcp_sources import SOURCE_ID, make_snapshot


def test_chat_uses_one_query_embedding_and_search_without_fetch_index_or_count(rag_backend, monkeypatch):
    client, embeddings, _ = rag_backend
    prepare_sources(monkeypatch)
    query_calls, searches, retrieved = [], [], []
    original_query, original_search, original_retrieve = embeddings.embed_query, client.query_points, client.retrieve
    def embed(question, **kwargs):
        query_calls.append(question)
        return original_query(question, **kwargs)
    def search(*args, **kwargs):
        searches.append(kwargs)
        return original_search(*args, **kwargs)
    def retrieve(*args, **kwargs):
        retrieved.append(kwargs)
        return original_retrieve(*args, **kwargs)
    monkeypatch.setattr(embeddings, "embed_query", embed)
    monkeypatch.setattr(client, "query_points", search)
    monkeypatch.setattr(client, "retrieve", retrieve)
    for name in ("fetch_sources", "ensure_document_indexed"):
        monkeypatch.setattr(service, name, lambda *a, **k: pytest.fail("Chat não atualiza fontes"))
    monkeypatch.setattr(client, "count", lambda *a, **k: pytest.fail("Chat não reconta o índice"))
    document_calls = embeddings.document_calls
    output = tool_module.build_external_knowledge_tool("residential").invoke({"question": "banho", "top_k": 20})
    assert output["status"] == "ok"
    assert len(query_calls) == len(searches) == len(retrieved) == 1
    assert embeddings.document_calls == document_calls
    assert {c["source_id"] for c in output["chunks"]} == {SOURCE_ID, "epa-residential-saving"}
    assert not any(c["origin"] == "external_manifest" for c in output["chunks"])


def test_failed_reindex_preserves_previous_complete_revision(rag_backend, monkeypatch):
    prepare_sources(monkeypatch)
    before = tool_module.search_external_knowledge.invoke({"question": "banho"})
    def fail(*args, **kwargs):
        raise TimeoutError("falha controlada")
    monkeypatch.setattr(service, "ensure_document_indexed", fail)
    updated = prepare_sources(monkeypatch, lambda source_id: make_snapshot("Nova revisão. " * 40, source_id=source_id))
    after = tool_module.search_external_knowledge.invoke({"question": "banho"})
    assert updated["updated"] == [] and updated["unavailable"]
    assert after["status"] == "ok"
    assert after["chunks"][0]["revision"] == before["chunks"][0]["revision"]


def test_process_restart_reads_persistent_marker_without_reindex(rag_backend, monkeypatch):
    prepare_sources(monkeypatch)
    mcp_client.clear_source_cache()
    monkeypatch.setattr(service, "fetch_sources", lambda *a, **k: pytest.fail("Sem MCP no chat"))
    # Não há estado de revisão ativa em memória: uma nova ferramenta usa o Qdrant.
    output = tool_module.build_external_knowledge_tool(None).invoke({"question": "banho"})
    assert output["status"] == "ok"


@pytest.mark.parametrize("change", [
    {"collected_at": (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()},
    {"collected_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()},
    {"embedding_model": "models/outro"}, {"revision": "f" * 64},
    {"url": "https://evil.invalid"}, {"chunk_count": 0}, {"origin": "external"},
    {"catalog_revision": "antigo"},
])
def test_invalid_or_expired_manifest_never_generates_embedding(rag_backend, monkeypatch, change):
    client, embeddings, _ = rag_backend
    prepare_sources(monkeypatch)
    client.set_payload(rag.COLLECTION, payload=change, points=[service.manifest_id(SOURCE_ID)])
    monkeypatch.setattr(embeddings, "embed_query", lambda *a, **k: pytest.fail("Marcador inválido"))
    output = tool_module.search_external_knowledge.invoke({"question": "banho"})
    assert output["status"] == "unavailable" and output["chunks"] == []


def test_incomplete_new_revision_never_gets_an_active_marker(rag_backend, monkeypatch):
    client, _, _ = rag_backend
    monkeypatch.setattr(service, "ensure_document_indexed", lambda *a, **k: (_ for _ in ()).throw(ValueError()))
    prepare_sources(monkeypatch)
    assert client.retrieve(rag.COLLECTION, ids=[service.manifest_id(SOURCE_ID)]) == []
    assert tool_module.search_external_knowledge.invoke({"question": "banho"})["status"] == "unavailable"


def test_same_revision_does_not_reembed_documents(rag_backend, monkeypatch):
    _, embeddings, _ = rag_backend
    prepare_sources(monkeypatch)
    count = embeddings.document_calls
    prepare_sources(monkeypatch)
    assert embeddings.document_calls == count


def test_external_source_lock_does_not_block_internal_indexing(rag_backend, monkeypatch):
    client, embeddings, _ = rag_backend
    entered, release = Event(), Event()
    class UpdatingSource:
        def __enter__(self):
            entered.set()
            assert release.wait(5)
        def __exit__(self, *args): pass
    external = rag.external_document(make_snapshot())
    internal = rag.RagDocument(rag.SOURCE, "teste", (rag.DocumentChunk(("Delta",), "Cadastro.", 1, 1),))
    monkeypatch.setitem(rag._SOURCE_LOCKS, external.source, UpdatingSource())
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        first = pool.submit(rag.ensure_document_indexed, external, client=client, embeddings=embeddings)
        assert entered.wait(2)
        second = pool.submit(rag.ensure_document_indexed, internal, client=client, embeddings=embeddings)
        second.result(timeout=2)
    finally:
        release.set()
        pool.shutdown(wait=True)
    first.result()


def test_external_chunks_share_one_short_citation_and_keep_diagnostics(rag_backend, monkeypatch):
    prepare_sources(monkeypatch, lambda _: thematic_snapshot())
    output = tool_module.search_external_knowledge.invoke({"question": "banho", "top_k": 3})
    assert len(output["chunks"]) > 1
    assert len({chunk["citation"] for chunk in output["chunks"]}) == 1
    assert all(chunk["revision"] and chunk["source_revision"] and chunk["collected_at"]
               and chunk["start_line"] and chunk["end_line"] for chunk in output["chunks"])
    assert "[URI omitida]" not in public_data(output)["chunks"][0]["citation"]


def test_url_exception_is_restricted_to_exact_catalog_urls():
    url = SOURCES[SOURCE_ID].url
    assert public_data(f"[Fonte]({url})") == f"[Fonte]({url})"
    assert "URI omitida" in public_data(url + "?password=segredo")
    assert "URI omitida" in public_data("mongodb://user:secret@localhost/db")


def test_mcp_batch_uses_one_client_and_preserves_per_source_failure(monkeypatch):
    opened, called = [], []
    class Client:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self):
            opened.append(True)
            return self
        async def __aexit__(self, *args): pass
        async def call_tool(self, name, args):
            called.append(args)
            source_id = args["source_id"]
            return SimpleNamespace(is_error=False, structured_content=(
                {"status": "unavailable"} if source_id == "epa-residential-saving" else
                {"status": "ok", "document": make_snapshot(source_id=source_id).model_dump()}))
    monkeypatch.setattr(mcp_client, "Client", Client)
    output = asyncio.run(mcp_client.call_sources(list(SOURCES), 2))
    assert len(opened) == 1 and len(called) == 3
    assert all(set(args) == {"source_id"} for args in called)
    assert output[SOURCE_ID] and output["epa-residential-saving"] is None


def test_concurrent_batch_cache_misses_share_fetch(monkeypatch):
    settings = load_settings({"APP_ENV": "test", "MCP_EXTERNAL_ENABLED": "true"})
    monkeypatch.setattr(mcp_client, "get_settings", lambda: settings)
    call = AsyncMock(return_value={SOURCE_ID: make_snapshot()})
    monkeypatch.setattr(mcp_client, "call_sources", call)
    mcp_client.clear_source_cache()
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            outputs = list(pool.map(lambda _: mcp_client.fetch_sources([SOURCE_ID]), range(3)))
        assert outputs[0] == outputs[1] == outputs[2]
        assert call.await_count == 1
    finally:
        mcp_client.clear_source_cache()


def test_token_accounting_does_not_block_embedding_and_is_cached(monkeypatch):
    embedding_usage.close_usage_clients()
    entered, release = Event(), Event()
    calls = []
    def slow_count(model, texts):
        calls.append(texts)
        entered.set()
        assert release.wait(3)
        return 42
    monkeypatch.setattr(diagnostics, "_count_embedding_tokens", slow_count)
    trace = Trace(mode="chat")
    try:
        with capture(trace):
            with diagnostics.embedding_call("teste", texts=["pergunta"]):
                pass
            assert entered.wait(1)  # embedding retornou enquanto a contagem ainda está bloqueada
            with diagnostics.embedding_call("teste", texts=["pergunta"]):
                pass
        pending = metrics.build_record(trace, "success", 1)
        assert pending["embedding_pending"] == pending["embedding_uncounted"] == 2
        assert pending["embedding_cost_usd"] == 0
        release.set()
        wait(trace.embedding_counts, timeout=2)
        final = metrics.build_record(trace, "success", 1)
        assert final["embedding_tokens"] == 84 and final["embedding_pending"] == 0
        assert len(calls) == 1
    finally:
        release.set()
        embedding_usage.close_usage_clients()


def test_full_accounting_queue_does_not_block_or_invent_cost(monkeypatch):
    monkeypatch.setattr(embedding_usage, "submit_count", lambda *args: None)
    trace = Trace(mode="chat")
    with capture(trace):
        with diagnostics.embedding_call("teste", texts=["pergunta"]):
            pass
    assert trace.models[0]["status"] == "success" and trace.models[0]["count_status"] == "unavailable"
    assert metrics.build_record(trace, "success", 1)["embedding_uncounted"] == 1


def test_counting_client_has_timeout_and_is_reused(monkeypatch):
    from google import genai
    clients, closed = [], []
    class Client:
        def __init__(self, **kwargs):
            clients.append(kwargs)
            self.models = SimpleNamespace(count_tokens=lambda **kwargs: SimpleNamespace(total_tokens=7))
        def close(self):
            closed.append(True)
    embedding_usage.close_usage_clients()
    monkeypatch.setattr(genai, "Client", Client)
    try:
        assert embedding_usage.count_tokens("modelo", ["texto"]) == 7
        assert embedding_usage.count_tokens("modelo", ["outro texto"]) == 7
        assert len(clients) == 1
        assert clients[0]["http_options"] == {"timeout": 5000, "retry_options": {"attempts": 1}}
    finally:
        embedding_usage.close_usage_clients()
    assert closed == [True]


def test_api_lifespan_starts_refresh_without_waiting_for_it(monkeypatch):
    from app import main
    events = []
    class Worker:
        def start(self): events.append("start")
        def stop(self): events.append("stop")
    monkeypatch.setattr(service, "ExternalRefreshWorker", Worker)
    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(mcp_external_enabled=True))
    async def run():
        async with main.lifespan(main.app):
            assert events == ["start"]
    asyncio.run(run())
    assert events == ["start", "stop"]


def test_background_refresh_reports_its_own_official_usage(rag_backend, monkeypatch):
    embedding_usage.close_usage_clients()
    def snapshots(source_ids, **kwargs):
        return {s: make_snapshot(source_id=s).model_copy(update={
            "collected_at": datetime.now(timezone.utc).isoformat(),
        }) for s in source_ids}
    monkeypatch.setattr(service, "fetch_sources", snapshots)
    monkeypatch.setattr(diagnostics, "_count_embedding_tokens", lambda *a: 17)
    try:
        output = service.refresh_with_diagnostics()
        assert output["status"] == "ok"
        assert output["metrics"]["embedding_tokens"] == 51
        assert output["metrics"]["embedding_uncounted"] == 0
        assert {"mcp_fetch", "external_index", "external_publish"} <= output["metrics"]["rag_phases_ms"].keys()
    finally:
        embedding_usage.close_usage_clients()


def test_refresh_cli_reports_safe_failure_and_closes_clients(monkeypatch, capsys):
    from scripts import refresh_external_knowledge as script
    close = AsyncMock()
    monkeypatch.setattr(script, "close_rag_clients", close)
    monkeypatch.setattr(script, "close_usage_clients", lambda: None)
    monkeypatch.setattr(script, "refresh_with_diagnostics", lambda: (_ for _ in ()).throw(ValueError("SEGREDO")))
    assert script.main() == 1
    assert "SEGREDO" not in capsys.readouterr().out
    close.assert_awaited_once()


@pytest.mark.parametrize("values", [
    {"MCP_REFRESH_INTERVAL_SECONDS": "0"}, {"MCP_REFRESH_INTERVAL_SECONDS": "texto"},
    {"MCP_MAX_STALE_SECONDS": "-1"}, {"MCP_MAX_STALE_SECONDS": "604801"},
    {"MCP_REFRESH_INTERVAL_SECONDS": "600", "MCP_MAX_STALE_SECONDS": "599"},
])
def test_refresh_configuration_is_validated(values):
    with pytest.raises(ConfigurationError):
        validate_mcp_config(settings=load_settings({"APP_ENV": "test", **values}))
