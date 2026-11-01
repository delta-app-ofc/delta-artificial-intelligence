"""Atualização das fontes fora do chat e consulta da última revisão completa."""

from dataclasses import asdict
from concurrent.futures import wait
from datetime import datetime, timezone
import hashlib
import json
import logging
import re
from threading import Event, Lock, Thread
from time import perf_counter
import uuid

from qdrant_client.models import FieldCondition, Filter, MatchValue, PointStruct

from app.config import get_settings, validate_mcp_config
from app.integrations.mcp.client import fetch_sources
from app.integrations.mcp.sources import SOURCES
from app.observability.diagnostics import Trace, capture, component, embedding_call
from app.services.rag import (
    COLLECTION, EXTERNAL_PARSER_VERSION, VECTOR_SIZE, create_embeddings, create_qdrant, embedding_model_name,
    ensure_document_indexed, external_document, validate_collection,
)

logger = logging.getLogger(__name__)
_REFRESH_LOCK = Lock()


def _catalog_revision(source_id):
    encoded = json.dumps(asdict(SOURCES[source_id]), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def manifest_id(source_id):
    """Modelo e catálogo diferentes nunca compartilham o marcador de ativação."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL,
                         f"external-active:{source_id}:{embedding_model_name()}:{_catalog_revision(source_id)}"))


def refresh_external_knowledge(*, force: bool = True) -> dict:
    """Publica cada marcador somente após confirmar todos os chunks da revisão.

    O marcador usa origem/fonte próprias na mesma coleção; nunca participa da
    busca documental nem da contagem dos chunks. Revisões antigas são mantidas.
    """
    settings = get_settings()
    validate_mcp_config(settings=settings)
    if not settings.mcp_external_enabled:
        return {"status": "disabled", "updated": [], "unavailable": []}
    if not _REFRESH_LOCK.acquire(blocking=False):
        return {"status": "busy", "updated": [], "unavailable": []}
    updated, failures = [], []
    try:
        client, embeddings = create_qdrant(), create_embeddings()
        with component("rag_refresh_schema"):
            validate_collection(client=client)
        with component("rag_mcp_fetch"):
            snapshots = fetch_sources(list(SOURCES), force=force)
        for source_id in SOURCES:
            try:
                snapshot = snapshots.get(source_id)
                if snapshot is None or snapshot.source_id != source_id:
                    raise ValueError("Fonte indisponível na atualização.")
                document = external_document(snapshot)
                with component("rag_external_index"):
                    ensure_document_indexed(document, client=client, embeddings=embeddings)
                with component("rag_external_publish"):
                    client.upsert(COLLECTION, points=[PointStruct(
                        id=manifest_id(source_id), vector=[1.0] + [0.0] * (VECTOR_SIZE - 1),
                        payload={**document.metadata, "origin": "external_manifest", "source": f"mcp-manifest:{source_id}",
                                 "source_id": source_id, "embedding_model": embedding_model_name(),
                                 "revision": document.revision, "chunk_count": len(document.chunks),
                                 "catalog_revision": _catalog_revision(source_id)},
                    )], wait=True)
                updated.append(source_id)
            except Exception as error:
                failures.append(source_id)
                logger.warning("Atualização da fonte %s falhou (%s).", source_id, type(error).__name__)
        return {"status": "partial" if failures else "ok", "updated": updated, "unavailable": failures}
    finally:
        _REFRESH_LOCK.release()


def load_active_sources(source_ids, *, client):
    """Lê os marcadores em lote; recusa vencidos, incompatíveis ou adulterados."""
    with component("rag_external_manifest"):
        points = client.retrieve(COLLECTION, ids=[manifest_id(s) for s in source_ids], with_payload=True)
    active = []
    now = datetime.now(timezone.utc)
    for point in points:
        data = point.payload or {}
        source_id = data.get("source_id")
        if source_id not in source_ids or str(point.id) != manifest_id(source_id):
            continue
        try:
            collected = datetime.fromisoformat(data["collected_at"])
            revision = data["revision"]
            source_revision = data["source_revision"]
            expected_revision = hashlib.sha256((EXTERNAL_PARSER_VERSION + "\n" + source_revision).encode()).hexdigest()
            source = SOURCES[source_id]
            if (data.get("origin") != "external_manifest"
                    or data.get("embedding_model") != embedding_model_name()
                    or data.get("catalog_revision") != _catalog_revision(source_id)
                    or any(data.get(key) != getattr(source, key) for key in ("url", "title", "topic", "language", "published_at"))
                    or data.get("audiences") != list(source.audiences)
                    or not re.fullmatch(r"[0-9a-f]{64}", revision)
                    or revision != expected_revision
                    or type(data.get("chunk_count")) is not int or data["chunk_count"] <= 0
                    or collected.tzinfo is None
                    or not 0 <= (now - collected).total_seconds() <= get_settings().mcp_max_stale_seconds):
                continue
        except (KeyError, TypeError, ValueError):
            continue
        active.append(data)
    return active


def search_active_sources(active, question, *, client, embeddings, top_k):
    """Um embedding e uma busca para todas as fontes autorizadas e suas revisões."""
    with component("rag_external_schema"):
        validate_collection(client=client)
    with component("rag_query_embedding"):
        with embedding_call(embedding_model_name(), texts=[question]):
            vector = embeddings.embed_query(question, task_type="RETRIEVAL_QUERY")
    revisions = [Filter(must=[
        FieldCondition(key="source", match=MatchValue(value=f"mcp:{item['source_id']}")),
        FieldCondition(key="revision", match=MatchValue(value=item["revision"])),
    ]) for item in active]
    filters = Filter(must=[
        FieldCondition(key="embedding_model", match=MatchValue(value=embedding_model_name())),
        FieldCondition(key="origin", match=MatchValue(value="external")),
        Filter(should=revisions),
    ])
    with component("rag_external_query"):
        response = client.query_points(COLLECTION, query=vector, query_filter=filters,
                                       limit=top_k, with_payload=True)
    metadata = {item["source_id"]: item for item in active}
    results = []
    for point in response.points:
        payload = point.payload or {}
        item = metadata.get(payload.get("source_id"))
        if item is None or payload.get("revision") != item["revision"]:
            continue
        # A coleta confirma o texto desta revisão mesmo quando os vetores já existiam.
        results.append({**payload, "id": str(point.id), "score": point.score,
                        "collected_at": item["collected_at"]})
    return results


def refresh_with_diagnostics():
    """Mede a manutenção separadamente das requisições e do ROI do chat."""
    from app.observability.metrics import build_record
    trace = Trace(mode="external_refresh")
    started = perf_counter()
    with capture(trace):
        result = refresh_external_knowledge()
    if trace.embedding_counts:
        wait(trace.embedding_counts, timeout=25)
    metrics = build_record(trace, result["status"], (perf_counter() - started) * 1000)
    return {**result, "metrics": {key: metrics[key] for key in (
        "total_ms", "rag_phases_ms", "embedding_tokens", "embedding_uncounted",
        "embedding_pending", "embedding_count_ms", "embedding_cost_usd",
    )}}


class ExternalRefreshWorker:
    """Uma thread por processo; a API inicia sem esperar rede ou indexação."""

    def __init__(self):
        self.stopped = Event()
        self.thread = Thread(target=self.run, name="external-knowledge-refresh", daemon=True)

    def start(self):
        validate_mcp_config()
        self.thread.start()

    def run(self):
        while not self.stopped.is_set():
            try:
                result = refresh_with_diagnostics()
                logger.info("Atualização externa: %s", result)
            except Exception as error:
                logger.warning("Atualização externa indisponível (%s).", type(error).__name__)
            self.stopped.wait(get_settings().mcp_refresh_interval_seconds)

    def stop(self):
        self.stopped.set()
        self.thread.join()
