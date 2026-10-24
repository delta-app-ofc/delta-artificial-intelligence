"""Segmentação Markdown e recuperação documental, sem gerar respostas."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import math
from pathlib import Path
import re
import uuid

from app.config import ConfigurationError, get_settings

COLLECTION = "rag_documents"
EMBEDDING_MODEL = "models/gemini-embedding-001"
VECTOR_SIZE = 3072
MAX_SECTION_CHARS = 6000
_PARSER_VERSION = "markdown-headings-v1"


@dataclass(frozen=True)
class DocumentChunk:
    """Trecho com hierarquia e localização na fonte original."""

    headings: tuple[str, ...]
    text: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class RagDocument:
    source: str
    revision: str
    chunks: tuple[DocumentChunk, ...]


def split_markdown(text: str) -> tuple[DocumentChunk, ...]:
    """Separa por #, ## e ###, preservando títulos e blocos de código.

    Não divide no caractere # dentro de frases. Títulos sem corpo não viram
    vetores vazios. Seções grandes devem ser subdivididas na fonte com ###.
    """
    headings: dict[int, str] = {}
    chunks = []
    body: list[str] = []
    start_line = 1
    fence: str | None = None
    fence_size = 0

    def flush(end_line: int) -> None:
        content = "\n".join(body).strip()
        if not content:
            return
        hierarchy = tuple(headings[level] for level in sorted(headings))
        if len(content) + sum(map(len, hierarchy)) > MAX_SECTION_CHARS:
            raise ValueError("Seção muito longa; subdivida o Markdown com subtítulos ###.")
        chunks.append(DocumentChunk(hierarchy, content, start_line, end_line))

    lines = text.splitlines()
    for line_number, line in enumerate(lines, 1):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if marker:
            run = marker[1]
            if fence is None:
                fence, fence_size = run[0], len(run)
            elif run[0] == fence and len(run) >= fence_size and not line[marker.end():].strip():
                fence = None
            body.append(line)
            continue
        heading = re.match(r"^ {0,3}(#{1,3})\s+(.+?)\s*$", line) if fence is None else None
        if heading:
            flush(line_number - 1)
            level = len(heading[1])
            headings = {key: value for key, value in headings.items() if key < level}
            headings[level] = re.sub(r"\s+#+$", "", heading[2]).strip()
            body = []
            start_line = line_number
        else:
            body.append(line)
    flush(len(lines))
    if not chunks:
        raise ValueError("O documento não possui conteúdo para indexar.")
    return tuple(chunks)


def load_document(path: str | Path, *, source: str = "delta-product-reference") -> RagDocument:
    """Lê a fonte explicitamente, sem depender do checkout do handbook."""
    if not source.strip():
        raise ValueError("Informe um identificador de fonte não vazio.")
    text = Path(path).read_text(encoding="utf-8-sig")
    revision = hashlib.sha256((_PARSER_VERSION + "\n" + text).encode("utf-8")).hexdigest()
    return RagDocument(source, revision, split_markdown(text))


def create_embeddings():
    """Usa o modelo textual Gemini com tarefas de documento e consulta distintas."""
    settings = get_settings()
    if not settings.gemini_api_key:
        raise ConfigurationError("GEMINI_API_KEY ausente para embeddings RAG.")
    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    return GoogleGenerativeAIEmbeddings(
        model=EMBEDDING_MODEL,
        api_key=settings.gemini_api_key,
        output_dimensionality=VECTOR_SIZE,
        vertexai=False,
        client_args={"timeout": 30},
    )


def create_qdrant():
    """Exige destino explícito e não reutiliza a coleção de memória."""
    from qdrant_client import QdrantClient

    settings = get_settings()
    if not settings.qdrant_url:
        raise ConfigurationError("QDRANT_URL ausente para a base documental RAG.")
    return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, timeout=30)


def _validate_vector(vector: list[float]) -> None:
    if len(vector) != VECTOR_SIZE or not all(math.isfinite(value) for value in vector) or not any(vector):
        raise ValueError("Embedding inválido: confira dimensão e valores do modelo RAG.")


def _document_filter(document: RagDocument):
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    return Filter(must=[
        FieldCondition(key=key, match=MatchValue(value=value))
        for key, value in {
            "source": document.source, "revision": document.revision,
            "embedding_model": EMBEDDING_MODEL,
        }.items()
    ])


def _check_collection(client) -> None:
    from qdrant_client.models import Distance

    vectors = client.get_collection(COLLECTION).config.params.vectors
    if not hasattr(vectors, "size") or vectors.size != VECTOR_SIZE or vectors.distance != Distance.COSINE:
        raise ValueError("Coleção RAG incompatível. Use vetores de 3072 dimensões e Cosine; nada foi apagado.")


def index_document(document: RagDocument, *, client, embeddings) -> int:
    """Grava uma revisão idempotente; nunca apaga coleções ou revisões antigas."""
    from qdrant_client.models import Distance, PayloadSchemaType, PointStruct, VectorParams

    if client.collection_exists(COLLECTION):
        _check_collection(client)
    else:
        client.create_collection(COLLECTION, vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE))
    for field in ("source", "revision", "embedding_model"):
        client.create_payload_index(COLLECTION, field, field_schema=PayloadSchemaType.KEYWORD, wait=True)

    texts = ["\n".join((*chunk.headings, chunk.text)) for chunk in document.chunks]
    vectors = embeddings.embed_documents(texts, task_type="RETRIEVAL_DOCUMENT")
    if len(vectors) != len(document.chunks):
        raise ValueError("O provedor não retornou um embedding por trecho.")
    points = []
    for index, (chunk, vector) in enumerate(zip(document.chunks, vectors)):
        _validate_vector(vector)
        identity = f"{document.source}:{document.revision}:{EMBEDDING_MODEL}:{index}"
        points.append(PointStruct(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, identity)), vector=vector,
            payload={**asdict(chunk), "source": document.source, "revision": document.revision,
                     "embedding_model": EMBEDDING_MODEL},
        ))
    client.upsert(COLLECTION, points=points, wait=True)
    return len(points)


def search_document(document: RagDocument, question: str, *, client, embeddings,
                    top_k: int = 3, score_threshold: float | None = None) -> list[dict]:
    """Converte a pergunta em vetor e retorna trechos e scores, sem validar relevância."""
    if not question.strip() or not 1 <= top_k <= 20:
        raise ValueError("Informe uma pergunta e top_k entre 1 e 20.")
    if score_threshold is not None and (not math.isfinite(score_threshold) or not -1 <= score_threshold <= 1):
        raise ValueError("score_threshold deve estar entre -1 e 1.")
    if not client.collection_exists(COLLECTION):
        raise ValueError("Base RAG não indexada. Execute a indexação primeiro.")
    _check_collection(client)
    query_filter = _document_filter(document)
    count = client.count(COLLECTION, count_filter=query_filter, exact=True).count
    if count != len(document.chunks):
        raise ValueError("Revisão ausente ou incompleta. Indexe o documento atual antes de consultar.")
    vector = embeddings.embed_query(question, task_type="RETRIEVAL_QUERY")
    _validate_vector(vector)
    response = client.query_points(
        COLLECTION, query=vector, query_filter=query_filter, limit=top_k,
        score_threshold=score_threshold, with_payload=True,
    )
    return [{"id": str(point.id), "score": point.score, **(point.payload or {})} for point in response.points]
