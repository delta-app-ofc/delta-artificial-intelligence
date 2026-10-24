"""Valida segmentação e busca Qdrant real em memória, sem chamar Gemini."""

import hashlib
import warnings

import pytest
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from app.services.rag import (
    COLLECTION, VECTOR_SIZE, RagDocument, create_embeddings, create_qdrant,
    index_document, load_document, search_document, split_markdown,
)
from app.config import ConfigurationError


class FakeEmbeddings:
    """Vetores controlados: testa o armazenamento, não a qualidade semântica."""

    def __init__(self):
        self.calls = []

    def vector(self, text):
        vector = [0.0] * VECTOR_SIZE
        vector[0 if "chuva" in text.casefold() else 1] = 1.0
        return vector

    def embed_documents(self, texts, *, task_type):
        self.calls.append((task_type, texts))
        return [self.vector(text) for text in texts]

    def embed_query(self, text, *, task_type):
        self.calls.append((task_type, text))
        return self.vector(text)


@pytest.fixture
def client():
    instance = QdrantClient(":memory:")
    instance.create_collection(
        COLLECTION, vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
    )
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Payload indexes have no effect.*")
        yield instance
    instance.close()


@pytest.fixture
def document(tmp_path):
    path = tmp_path / "base.md"
    path.write_text("# Delta\n\nReferência funcional.\n\n## Clima\n\n### Chuva\n\nÁgua de chuva.\n\n## Conta\n\nLogin e senha.\n", encoding="utf-8")
    return load_document(path)


def test_split_preserves_hierarchy_body_and_lines():
    chunks = split_markdown("# Delta\n## Clima\n### Chuva\nÁgua.\n## Conta\nLogin.")
    assert len(chunks) == 2
    assert chunks[0].headings == ("Delta", "Clima", "Chuva")
    assert chunks[0].text == "Água."
    assert (chunks[0].start_line, chunks[0].end_line) == (3, 4)
    assert chunks[1].headings == ("Delta", "Conta")


def test_inline_hashes_and_deeper_headings_are_content():
    chunks = split_markdown("# Delta\nTexto # comum.\n#### Detalhe\nFim.")
    assert len(chunks) == 1
    assert "Texto # comum." in chunks[0].text
    assert "#### Detalhe" in chunks[0].text


@pytest.mark.parametrize("text", ["", "# Só título\n## Vazio", "# Grande\n" + "a" * 6001])
def test_rejects_empty_and_oversized_sections(text):
    with pytest.raises(ValueError):
        split_markdown(text)


def test_revision_changes_with_document_and_bom_is_supported(tmp_path):
    path = tmp_path / "base.md"
    path.write_text("# Delta\nVersão um.", encoding="utf-8-sig")
    first = load_document(path)
    assert first == load_document(path)
    path.write_text("# Delta\nVersão dois.", encoding="utf-8")
    assert first.revision != load_document(path).revision


def test_index_is_idempotent_and_search_returns_source(client, document):
    embeddings = FakeEmbeddings()
    assert index_document(document, client=client, embeddings=embeddings) == 3
    index_document(document, client=client, embeddings=embeddings)
    assert client.count(COLLECTION).count == 3
    results = search_document(document, "chuva", client=client, embeddings=embeddings, top_k=1)
    assert results[0]["headings"] == ["Delta", "Clima", "Chuva"]
    assert results[0]["text"] == "Água de chuva."
    assert results[0]["revision"] == document.revision
    assert results[0]["source"] == document.source
    assert results[0]["score"] == pytest.approx(1)
    assert embeddings.calls[0][0] == "RETRIEVAL_DOCUMENT"
    assert embeddings.calls[-1] == ("RETRIEVAL_QUERY", "chuva")


def test_search_excludes_old_revisions_and_other_sources(client, document):
    embeddings = FakeEmbeddings()
    index_document(document, client=client, embeddings=embeddings)
    updated = RagDocument(document.source, hashlib.sha256(b"new").hexdigest(), (document.chunks[-1],))
    foreign = RagDocument("other-source", updated.revision, document.chunks)
    for item in (updated, foreign):
        index_document(item, client=client, embeddings=embeddings)
    results = search_document(updated, "chuva", client=client, embeddings=embeddings)
    assert len(results) == 1
    assert results[0]["headings"] == ["Delta", "Conta"]
    assert search_document(updated, "chuva", client=client, embeddings=embeddings, score_threshold=0.9) == []


def test_search_requires_complete_index_before_embedding(client, document):
    embeddings = FakeEmbeddings()
    index_document(document, client=client, embeddings=embeddings)
    embeddings.calls.clear()
    absent = RagDocument(document.source, "not-indexed", document.chunks)
    with pytest.raises(ValueError, match="incompleta"):
        search_document(absent, "chuva", client=client, embeddings=embeddings)
    assert embeddings.calls == []


@pytest.mark.parametrize("action", ["index", "search"])
def test_missing_collection_stops_before_embedding(document, action):
    embeddings = FakeEmbeddings()
    empty_client = QdrantClient(":memory:")
    try:
        with pytest.raises(ValueError):
            if action == "index":
                index_document(document, client=empty_client, embeddings=embeddings)
            else:
                search_document(document, "chuva", client=empty_client, embeddings=embeddings)
        assert not empty_client.collection_exists(COLLECTION)
    finally:
        empty_client.close()
    assert embeddings.calls == []


def test_provider_failure_is_not_empty_results(client, document):
    embeddings = FakeEmbeddings()
    index_document(document, client=client, embeddings=embeddings)

    def fail(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    embeddings.embed_query = fail
    with pytest.raises(RuntimeError):
        search_document(document, "chuva", client=client, embeddings=embeddings)


def test_clients_require_explicit_configuration(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("QDRANT_URL", raising=False)
    with pytest.raises(ConfigurationError, match="GEMINI_API_KEY"):
        create_embeddings()
    with pytest.raises(ConfigurationError, match="QDRANT_URL"):
        create_qdrant()
