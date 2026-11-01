"""Segmentação Markdown e recuperação documental, sem gerar respostas."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import math
from pathlib import Path
import re
from threading import Lock
import uuid
import textwrap

from app.config import BASE_DIR, ConfigurationError, get_settings
from app.observability.diagnostics import embedding_call
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from qdrant_client import QdrantClient
from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    Distance,
)


COLLECTION = "rag_documents"
SOURCE = "delta-product-reference"
VECTOR_SIZE = 3072
MAX_SECTION_CHARS = 6000
_PARSER_VERSION = "markdown-headings-v2"
_INDEX_LOCK = Lock()
_CLIENTS_LOCK = Lock()
_CLIENTS: dict = {}


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
    metadata: dict[str, str] = field(default_factory=dict)


def external_document(snapshot) -> RagDocument:
    """Segmenta texto externo sem interpretar títulos ou instruções como Markdown.

    As linhas citadas são as do texto normalizado. A revisão inclui a versão
    do segmentador para não reutilizar vetores de uma segmentação diferente.
    """
    lines = [part for line in snapshot.text.splitlines()
             for part in textwrap.wrap(line, width=1800, break_on_hyphens=False)]
    chunks = []
    body: list[str] = []
    start = 1
    for number, line in enumerate(lines, 1):
        if body and len("\n".join(body)) + len(line) + 1 > 1800:
            chunks.append(DocumentChunk((snapshot.title, snapshot.topic), "\n".join(body), start, number - 1))
            body = []
            start = number
        body.append(line)
    if body:
        chunks.append(DocumentChunk((snapshot.title, snapshot.topic), "\n".join(body), start, len(lines)))
    revision = hashlib.sha256(("external-text-v1\n" + snapshot.revision).encode("utf-8")).hexdigest()
    return RagDocument(
        source=f"mcp:{snapshot.source_id}", revision=revision, chunks=tuple(chunks),
        metadata={"origin": "external", "source_id": snapshot.source_id, "url": snapshot.url,
                  "title": snapshot.title, "topic": snapshot.topic, "published_at": snapshot.published_at,
                  "collected_at": snapshot.collected_at, "source_revision": snapshot.revision},
    )


def validate_collection(*, client) -> None:
    """Recusa esquema incompatível antes de gerar embeddings; nunca recria a coleção."""
    if not client.collection_exists(COLLECTION):
        raise ValueError("Coleção RAG ausente. Crie rag_documents no Qdrant antes de indexar.")
    vectors = client.get_collection(COLLECTION).config.params.vectors
    if (isinstance(vectors, dict) or vectors is None or vectors.size != VECTOR_SIZE
            or vectors.distance != Distance.COSINE):
        raise ValueError("rag_documents deve usar um vetor sem nome, 3072 dimensões e distância Cosine.")


def split_markdown(text: str) -> tuple[DocumentChunk, ...]:
    """Separa por #, ## e ###, preservando a hierarquia de títulos.

    Não divide no caractere # dentro de frases. Títulos sem corpo não viram
    vetores vazios. Seções grandes devem ser subdivididas na fonte com ###.
    """
    headings: dict[int, str] = {}
    chunks = []
    body: list[str] = []
    start_line = 1

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
        heading = re.match(r"^ {0,3}(#{1,3})\s+(.+?)\s*$", line)

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


def load_document(path: str | Path | None = None, *, source: str = SOURCE) -> RagDocument:
    """Lê a fonte das informações."""

    if not source.strip():
        raise ValueError("Informe um identificador de fonte não vazio.")

    path = Path(path if path is not None else get_settings().rag_document_path or "")
    if not path.is_absolute():
        path = BASE_DIR / path
    text = path.read_text(encoding="utf-8-sig")
    revision = hashlib.sha256((_PARSER_VERSION + "\n" + text).encode("utf-8")).hexdigest()

    return RagDocument(source, revision, split_markdown(text))


def embedding_model_name() -> str:
    """Normaliza o modelo configurado para o mesmo identificador no payload."""
    model = get_settings().gemini_embedding_model
    if not model:
        raise ConfigurationError("GEMINI_EMBEDDING_MODEL ausente para embeddings RAG.")
    return "models/" + model.removeprefix("models/")


def create_embeddings():
    """Usa o modelo textual Gemini com tarefas de documento e consulta distintas."""

    settings = get_settings()
    if not settings.gemini_api_key:
        raise ConfigurationError("GEMINI_API_KEY ausente para embeddings RAG.")

    with _CLIENTS_LOCK:
        if "embeddings" not in _CLIENTS:
            _CLIENTS["embeddings"] = GoogleGenerativeAIEmbeddings(
                model=embedding_model_name(),
                api_key=settings.gemini_api_key,
                output_dimensionality=VECTOR_SIZE,
                vertexai=False,
                client_args={"timeout": 30},
            )
        return _CLIENTS["embeddings"]


def create_qdrant():
    """Exige destino explícito e não reutiliza a coleção de memória."""

    settings = get_settings()
    if not settings.qdrant_url:
        raise ConfigurationError("QDRANT_URL ausente para a base documental RAG.")
    with _CLIENTS_LOCK:
        if "qdrant" not in _CLIENTS:
            _CLIENTS["qdrant"] = QdrantClient(
                url=settings.qdrant_url, api_key=settings.qdrant_api_key, timeout=30,
            )
        return _CLIENTS["qdrant"]


async def close_rag_clients() -> None:
    """Fecha os clientes RAG inicializados e limpa o cache sem criar conexões."""
    with _CLIENTS_LOCK:
        clients = dict(_CLIENTS)
        _CLIENTS.clear()

    close_error = None
    for name, client in clients.items():
        try:
            if name == "qdrant":
                client.close()
            else:
                try:
                    client.client.close()
                finally:
                    await client.client.aio.aclose()
        except Exception as error:
            if close_error is None:
                close_error = error
    if close_error is not None:
        raise RuntimeError("Falha ao fechar clientes RAG.") from close_error


def index_document(document: RagDocument, *, client, embeddings) -> int:
    """Reprocessa com IDs estáveis por fonte/revisão/modelo/posição.

    Repetir a mesma revisão sobrescreve seus pontos, sem duplicá-los. Revisões
    antigas ficam armazenadas, mas search_document consulta somente a atual.
    Embeddings são gerados antes da gravação; uma falha nessa etapa preserva o índice.
    """

    validate_collection(client=client)

    model = embedding_model_name()

    texts = ["\n".join((*chunk.headings, chunk.text)) for chunk in document.chunks]
    with embedding_call(model):
        vectors = embeddings.embed_documents(texts, task_type="RETRIEVAL_DOCUMENT")

    if len(vectors) != len(document.chunks):
        raise ValueError("O provedor não retornou um embedding por trecho.")
    points = []

    for index, (chunk, vector) in enumerate(zip(document.chunks, vectors)):
        identity = f"{document.source}:{document.revision}:{model}:{index}"
        points.append(PointStruct(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, identity)), vector=vector,
            payload={"origin": "internal", **document.metadata, **asdict(chunk),
                     "source": document.source, "revision": document.revision,
                     "embedding_model": model},
        ))
    client.upsert(COLLECTION, points=points, wait=True)

    return len(points)


def _revision_filter(document: RagDocument) -> Filter:
    """Aplica o mesmo recorte de fonte, revisão e modelo em todas as operações."""
    return Filter(must=[
        FieldCondition(key=key, match=MatchValue(value=value))
        for key, value in {
            "source": document.source, "revision": document.revision,
            "embedding_model": embedding_model_name(),
        }.items()
    ])


def _revision_is_complete(document: RagDocument, *, client) -> bool:
    count = client.count(
        COLLECTION, count_filter=_revision_filter(document), exact=True,
    ).count
    return count == len(document.chunks)



def ensure_document_indexed(document: RagDocument, *, client, embeddings) -> None:
    """Garante os índices de payload antes de consultar a revisão."""

    with _INDEX_LOCK:
        validate_collection(client=client)

        # Cria os índices necessários antes de utilizar filtros
        existing_indexes = client.get_collection(COLLECTION).payload_schema or {}

        for field in ("source", "revision", "embedding_model"):
            if field not in existing_indexes:
                client.create_payload_index(
                    collection_name=COLLECTION,
                    field_name=field,
                    field_schema=PayloadSchemaType.KEYWORD,
                    wait=True,
                )

        # Agora podemos consultar utilizando os filtros
        if _revision_is_complete(document, client=client):
            return

        index_document(document, client=client, embeddings=embeddings)

        if not _revision_is_complete(document, client=client):
            raise ValueError(
                "A indexação da revisão atual não foi concluída."
            )


def search_document(document: RagDocument, question: str, *, client, embeddings,
                    top_k: int = 3, score_threshold: float | None = None) -> list[dict]:
    """Converte a pergunta em vetor e retorna trechos e scores, sem validar relevância."""

    if not question.strip() or not 1 <= top_k <= 20:
        raise ValueError("Informe uma pergunta e top_k entre 1 e 20.")

    if score_threshold is not None and (not math.isfinite(score_threshold) or not -1 <= score_threshold <= 1):
        raise ValueError("score_threshold deve estar entre -1 e 1.")

    validate_collection(client=client)

    if not _revision_is_complete(document, client=client):
        raise ValueError("Revisão ausente ou incompleta. Indexe o documento atual antes de consultar.")

    with embedding_call(embedding_model_name()):
        vector = embeddings.embed_query(question, task_type="RETRIEVAL_QUERY")
    response = client.query_points(
        COLLECTION, query=vector, query_filter=_revision_filter(document), limit=top_k,
        score_threshold=score_threshold, with_payload=True,
    )

    return [{"id": str(point.id), "score": point.score, **(point.payload or {})} for point in response.points]
