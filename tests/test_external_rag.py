"""Recuperação real no Qdrant em memória; embeddings temáticos controlados."""

from dataclasses import replace
import json
from unittest.mock import patch

from langchain_core.messages import AIMessage, ToolMessage
from pydantic import ValidationError
import pytest
from qdrant_client import QdrantClient, models

from app.agents.rag import RagAgent
from app.config import load_settings
from app.integrations.mcp.sources import ExternalSourceError
from app.services import rag
from app.tools import external_knowledge as external_tool
from app.tools.rag import search_knowledge_base
from test_mcp_sources import SOURCE_ID, make_snapshot


class TopicEmbeddings:
    """Vocabulário artificial de teste; não mede qualidade semântica do Gemini."""

    def __init__(self):
        self.document_calls = 0

    def vector(self, text):
        words = text.casefold()
        vector = [float(words.count(word)) for word in ("banho", "jardim", "cadastro", "vazamento")]
        if not any(vector):
            vector.append(1.0)
        return vector + [0.0] * (rag.VECTOR_SIZE - len(vector))

    def embed_documents(self, texts, **kwargs):
        self.document_calls += 1
        return [self.vector(text) for text in texts]

    def embed_query(self, text, **kwargs):
        return self.vector(text)


@pytest.fixture
def rag_backend(monkeypatch):
    client = QdrantClient(":memory:")
    client.create_collection(rag.COLLECTION, vectors_config=models.VectorParams(
        size=rag.VECTOR_SIZE, distance=models.Distance.COSINE,
    ))
    embeddings = TopicEmbeddings()
    settings = load_settings({"APP_ENV": "test", "MCP_EXTERNAL_ENABLED": "true",
                              "GEMINI_API_KEY": "chave-sintetica", "QDRANT_URL": "http://unused.test"})
    monkeypatch.setattr(rag, "get_settings", lambda: settings)
    monkeypatch.setattr(external_tool, "get_settings", lambda: settings)
    monkeypatch.setattr(external_tool, "create_qdrant", lambda: client)
    monkeypatch.setattr(external_tool, "create_embeddings", lambda: embeddings)
    yield client, embeddings, settings
    client.close()


def thematic_snapshot():
    # Cada bloco ocupa um trecho distinto, com rótulos inequívocos e sem aleatoriedade.
    return make_snapshot("\n".join([
        "No banho, feche o chuveiro enquanto se ensaboa. " * 35,
        "No jardim, use regador para regar as plantas. " * 35,
    ]))


@pytest.mark.parametrize("question,expected", [("banho", "No banho"), ("jardim", "No jardim")])
def test_top_k_relevance_and_source_filters(rag_backend, monkeypatch, question, expected):
    monkeypatch.setattr(external_tool, "fetch_source", lambda source_id: thematic_snapshot())
    output = external_tool.search_external_knowledge.invoke({
        "question": question, "top_k": 1, "topic": "water_conservation", "source_id": SOURCE_ID,
    })
    assert output["status"] == "ok" and len(output["chunks"]) == 1
    chunk = output["chunks"][0]
    assert expected in chunk["text"]
    assert chunk["origin"] == "external" and chunk["source"] == f"mcp:{SOURCE_ID}"
    assert all(str(chunk[key]) in chunk["citation"] for key in ("url", "title", "revision", "collected_at"))
    assert "texto extraído" in chunk["citation"]


def test_unknown_metadata_does_not_fetch_or_fallback(rag_backend, monkeypatch):
    def unexpected(*args):
        pytest.fail("Filtro sem correspondência não deve consultar MCP.")
    monkeypatch.setattr(external_tool, "fetch_source", unexpected)
    for filters in ({"topic": "weather"}, {"source_id": "http://127.0.0.1/private"}):
        assert external_tool.search_external_knowledge.invoke({"question": "banho", **filters}) == {
            "status": "insufficient_data", "chunks": [],
        }


def test_revisions_sources_and_memory_collection_remain_isolated(rag_backend):
    client, embeddings, _ = rag_backend
    old = rag.external_document(make_snapshot("Banho antigo. " * 40))
    new = rag.external_document(make_snapshot("Jardim atualizado. " * 40))
    internal = rag.RagDocument(rag.SOURCE, "internal-v1", (
        rag.DocumentChunk(("Cadastro Delta",), "Cadastro do hidrômetro.", 1, 2),
    ))
    for document in (old, new, internal):
        rag.ensure_document_indexed(document, client=client, embeddings=embeddings)
    count = embeddings.document_calls
    rag.ensure_document_indexed(new, client=client, embeddings=embeddings)
    assert embeddings.document_calls == count
    hits = rag.search_document(new, "banho", client=client, embeddings=embeddings)
    assert all(hit["revision"] == new.revision and hit["origin"] == "external" for hit in hits)
    local = rag.search_document(internal, "cadastro", client=client, embeddings=embeddings)
    assert all(hit["source"] == rag.SOURCE and hit["origin"] == "internal" for hit in local)
    assert {item.name for item in client.get_collections().collections} == {rag.COLLECTION}


def test_incomplete_revision_is_repaired(rag_backend):
    client, embeddings, _ = rag_backend
    document = rag.external_document(thematic_snapshot())
    rag.ensure_document_indexed(document, client=client, embeddings=embeddings)
    points, _ = client.scroll(rag.COLLECTION, limit=20)
    client.delete(rag.COLLECTION, points_selector=models.PointIdsList(points=[points[0].id]))
    with pytest.raises(ValueError, match="incompleta"):
        rag.search_document(document, "banho", client=client, embeddings=embeddings)
    rag.ensure_document_indexed(document, client=client, embeddings=embeddings)
    assert client.count(rag.COLLECTION).count == len(document.chunks)


def test_incompatible_collection_fails_before_embeddings_without_recreating(rag_backend):
    _, embeddings, _ = rag_backend
    client = QdrantClient(":memory:")
    try:
        client.create_collection(rag.COLLECTION, vectors_config=models.VectorParams(
            size=768, distance=models.Distance.COSINE,
        ))
        with pytest.raises(ValueError, match="3072"):
            rag.ensure_document_indexed(rag.external_document(make_snapshot()), client=client, embeddings=embeddings)
        assert embeddings.document_calls == 0
        assert client.get_collection(rag.COLLECTION).config.params.vectors.size == 768
    finally:
        client.close()


def test_default_vector_empty_name_map_supports_indexing_and_search(rag_backend):
    _, embeddings, _ = rag_backend
    client = QdrantClient(":memory:")
    try:
        client.create_collection(rag.COLLECTION, vectors_config={"": models.VectorParams(
            size=rag.VECTOR_SIZE, distance=models.Distance.COSINE,
        )})
        document = rag.external_document(make_snapshot())
        rag.ensure_document_indexed(document, client=client, embeddings=embeddings)
        results = rag.search_document(document, "banho", client=client, embeddings=embeddings)
        assert results and results[0]["source"] == document.source
        assert client.count(rag.COLLECTION).count == len(document.chunks)
        assert set(client.get_collection(rag.COLLECTION).config.params.vectors) == {""}
    finally:
        client.close()


@pytest.mark.parametrize("names,size", [(["dense"], 3072), (["", "dense"], 3072), ([""], 768)])
def test_schema_guard_still_rejects_other_named_vectors_or_wrong_dimensions(rag_backend, names, size):
    _, embeddings, _ = rag_backend
    client = QdrantClient(":memory:")
    try:
        client.create_collection(rag.COLLECTION, vectors_config={name: models.VectorParams(
            size=size, distance=models.Distance.COSINE,
        ) for name in names})
        with pytest.raises(ValueError, match="3072"):
            rag.ensure_document_indexed(rag.external_document(make_snapshot()), client=client, embeddings=embeddings)
        assert embeddings.document_calls == 0
        assert set(client.get_collection(rag.COLLECTION).config.params.vectors) == set(names)
    finally:
        client.close()


def test_external_failure_is_unavailable_and_does_not_search_old_revision(rag_backend, monkeypatch):
    def unavailable(source_id):
        raise ExternalSourceError("DETALHE_PRIVADO")
    monkeypatch.setattr(external_tool, "fetch_source", unavailable)
    output = external_tool.search_external_knowledge.invoke({"question": "banho"})
    assert output == {"status": "unavailable", "chunks": [], "unavailable_sources": [SOURCE_ID]}
    assert "DETALHE_PRIVADO" not in json.dumps(output)


def test_disabled_external_search_does_not_open_clients(rag_backend, monkeypatch):
    settings = replace(rag_backend[2], mcp_external_enabled=False)
    monkeypatch.setattr(external_tool, "get_settings", lambda: settings)
    monkeypatch.setattr(external_tool, "create_qdrant", lambda: pytest.fail("MCP desabilitado"))
    assert external_tool.search_external_knowledge.invoke({"question": "banho"})["status"] == "unavailable"


@pytest.mark.parametrize("top_k", [0, 21])
def test_tools_bound_top_k(top_k):
    for tool in (search_knowledge_base, external_tool.search_external_knowledge):
        with pytest.raises(ValidationError):
            tool.invoke({"question": "banho", "top_k": top_k})


def test_agent_records_external_context_and_builds_citations_from_tool(rag_backend, monkeypatch):
    monkeypatch.setattr(external_tool, "fetch_source", lambda source_id: make_snapshot())
    output = external_tool.search_external_knowledge.invoke({"question": "banho"})
    messages = [
        AIMessage(content="", tool_calls=[{"name": "search_external_knowledge", "args": {"question": "banho"}, "id": "mcp-1"}]),
        ToolMessage(content=json.dumps(output), name="search_external_knowledge", tool_call_id="mcp-1"),
        AIMessage(content="Feche o chuveiro ao se ensaboar.\n\nFontes consultadas:\n- FONTE INVENTADA"),
    ]
    with patch("app.agents.rag.create_agent") as create:
        create.return_value.invoke.return_value = {"messages": messages}
        result = RagAgent(7, llm=object()).run("Como economizar água?")
    assert result.tool_calls[0].output == output
    assert result.sources == [output["chunks"][0]["citation"]]
    assert "FONTE INVENTADA" not in result.response
    assert result.sources[0] in result.response


@pytest.mark.parametrize("content", ['{"status":"unavailable","chunks":[]}', '[]', 'invalid'])
def test_agent_does_not_publish_answer_without_retrieved_sources(content):
    messages = [
        AIMessage(content="", tool_calls=[{"name": "search_external_knowledge", "args": {"question": "banho"}, "id": "mcp-1"}]),
        ToolMessage(content=content, name="search_external_knowledge", tool_call_id="mcp-1"),
        AIMessage(content="AFIRMAÇÃO SEM FONTE"),
    ]
    with patch("app.agents.rag.create_agent") as create:
        create.return_value.invoke.return_value = {"messages": messages}
        result = RagAgent(7, llm=object()).run("Como economizar água?")
    assert not result.sources and "AFIRMAÇÃO SEM FONTE" not in result.response


@pytest.mark.parametrize("access_kind,expected", [
    ("residential", {"midr-water-conservation", "epa-residential-saving"}),
    ("organizational", {"midr-water-conservation", "epa-commercial-facilities"}),
    (None, {"midr-water-conservation"}),
    ("unknown", set()),
])
def test_backend_profile_selects_only_applicable_sources(rag_backend, monkeypatch, access_kind, expected):
    fetched = []
    def fetch(source_id):
        fetched.append(source_id)
        return make_snapshot(source_id=source_id)
    monkeypatch.setattr(external_tool, "fetch_source", fetch)
    tool = external_tool.build_external_knowledge_tool(access_kind)
    # Mesmo com tentativa de substituir o perfil nos argumentos, o fechamento permanece confiável.
    output = tool.invoke({"question": "banho", "top_k": 20, "access_kind": "organizational"})
    assert set(fetched) == expected
    assert {chunk["source_id"] for chunk in output["chunks"]} == expected
    assert "access_kind" not in tool.args
    assert output["status"] == ("ok" if expected else "insufficient_data")


def test_residential_profile_cannot_request_commercial_source(rag_backend, monkeypatch):
    monkeypatch.setattr(external_tool, "fetch_source", lambda source_id: pytest.fail("Fonte comercial não permitida"))
    output = external_tool.build_external_knowledge_tool("residential").invoke({
        "question": "instalações", "source_id": "epa-commercial-facilities",
    })
    assert output == {"status": "insufficient_data", "chunks": []}


def test_partial_failure_keeps_successful_sources_and_reports_missing_one(rag_backend, monkeypatch):
    def fetch(source_id):
        if source_id == "epa-residential-saving":
            raise ExternalSourceError("MENSAGEM PRIVADA DO SERVIÇO")
        return make_snapshot(source_id=source_id)
    monkeypatch.setattr(external_tool, "fetch_source", fetch)
    output = external_tool.build_external_knowledge_tool("residential").invoke({"question": "banho"})
    assert output["status"] == "ok"
    assert output["unavailable_sources"] == ["epa-residential-saving"]
    assert {chunk["source_id"] for chunk in output["chunks"]} == {"midr-water-conservation"}
    assert "MENSAGEM PRIVADA" not in json.dumps(output)
    assert "publicação: não informada" in output["chunks"][0]["citation"]


def test_agent_binds_backend_profile_and_contains_watersense_restriction(rag_backend, monkeypatch):
    fetched = []
    def fetch(source_id):
        fetched.append(source_id)
        return make_snapshot(source_id=source_id)
    monkeypatch.setattr(external_tool, "fetch_source", fetch)
    with patch("app.agents.rag.create_agent") as create:
        RagAgent(7, llm=object(), access_kind="organizational")
        options = create.call_args.kwargs
    external = next(tool for tool in options["tools"] if tool.name == "search_external_knowledge")
    external.invoke({"question": "instalações"})
    assert fetched == ["midr-water-conservation", "epa-commercial-facilities"]
    assert "Não indique, recomende ou promova WaterSense" in options["system_prompt"]
    assert "URL original" in options["system_prompt"]
