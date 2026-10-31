"""Memória de longo prazo com Qdrant + Gemini embeddings.

Coleção: session_summaries (3072 dimensões, modelo definido no config).
Filtragem por user_id em todas as buscas.
"""

from __future__ import annotations

import uuid
from functools import lru_cache
from time import perf_counter
from typing import Callable, TypeVar

from app.config import ConfigurationError, get_settings
from app.observability.diagnostics import component, current_trace, embedding_call
from app.memory.session import load_history_validated


_COLLECTION = "session_summaries"
_VECTOR_SIZE = 3072

_collection_initialized = False
_T = TypeVar("_T")


def _run_phase(phase: str, action: Callable[[], _T]) -> _T:
    trace = current_trace()
    component_name = f"long_term_memory_{phase}"
    started = perf_counter()
    if trace:
        trace.event(
            "memory.phase.start",
            component=component_name,
            operation=phase,
            status="running",
            metadata={"phase": phase},
        )
    try:
        with component(component_name):
            try:
                result = action()
            except Exception as error:
                if trace:
                    trace.error(
                        component_name,
                        error,
                        operation=phase,
                        metadata={"phase": phase},
                    )
                raise
    except Exception as error:
        record = None
        if trace:
            record = trace.error(
                component_name,
                error,
                operation=phase,
                metadata={"phase": phase},
            )
            trace.event(
                "memory.phase.end",
                component=component_name,
                operation=phase,
                status="error",
                duration_ms=round((perf_counter() - started) * 1000, 1),
                metadata={
                    "phase": phase,
                    "outcome": "failed",
                    **({"error_id": record["error_id"]} if record else {}),
                },
            )
        raise

    if trace:
        trace.event(
            "memory.phase.end",
            component=component_name,
            operation=phase,
            status="success",
            duration_ms=round((perf_counter() - started) * 1000, 1),
            metadata={"phase": phase, "outcome": "completed"},
        )
    return result


@lru_cache(maxsize=1)
def _qdrant():
    from qdrant_client import QdrantClient

    settings = get_settings()

    return QdrantClient(
        url=settings.qdrant_url or "http://localhost:6333",
        api_key=settings.qdrant_api_key,
    )


@lru_cache(maxsize=1)
def _embed_model():
    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    settings = get_settings()

    if not settings.gemini_embedding_model:
        raise ConfigurationError("GEMINI_EMBEDDING_MODEL ausente ou vazio.")

    return GoogleGenerativeAIEmbeddings(
        model=settings.gemini_embedding_model,
        google_api_key=settings.gemini_api_key,
        output_dimensionality=_VECTOR_SIZE,
    )


def _ensure_collection() -> None:
    global _collection_initialized
    if _collection_initialized:
        return

    from qdrant_client.models import Distance, PayloadSchemaType, VectorParams

    client = _qdrant()
    existing = {c.name for c in client.get_collections().collections}

    needs_create = _COLLECTION not in existing
    if not needs_create:
        # Nunca apaga a coleção: dimensão errada é um problema de configuração a corrigir à mão.
        info = client.get_collection(_COLLECTION)
        current_size = info.config.params.vectors.size
        if current_size != _VECTOR_SIZE:
            raise ConfigurationError(
                f"A coleção {_COLLECTION} tem dimensão {current_size}, mas o esperado é {_VECTOR_SIZE}."
            )

    if needs_create:
        client.create_collection(
            _COLLECTION,
            vectors_config=VectorParams(size=_VECTOR_SIZE, distance=Distance.COSINE),
        )

    # Qdrant Cloud exige índice de payload para filtros por campo.
    try:
        client.create_payload_index(
            collection_name=_COLLECTION,
            field_name="user_id",
            field_schema=PayloadSchemaType.INTEGER,
        )
    except Exception as error:
        if trace := current_trace():
            trace.error(
                "long_term_memory",
                error,
                operation="create_user_index",
                metadata={"phase": "create_user_index"},
            )
        pass  # mantém o comportamento atual quando o índice já existe

    _collection_initialized = True


def save_summary(user_id: int, session_id: str, messages: list[dict]) -> None:
    """Gera resumo da conversa com llm_rapido, embeda e grava no Qdrant."""
    if not messages:
        return

    from app.services.llms import llm_rapido
    from langchain_core.messages import HumanMessage

    transcript = "\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in messages
    )
    summary_msg = _run_phase(
        "summary_generation",
        lambda: llm_rapido.invoke(
            [HumanMessage(content=f"Resuma em até 3 frases esta conversa:\n\n{transcript}")]
        ),
    )
    from app.agents._runtime import _message_text

    summary_text = _message_text(summary_msg) if hasattr(summary_msg, "content") else str(summary_msg)

    embed_model = _run_phase("create_embeddings", _embed_model)

    def embed_summary():
        with embedding_call(get_settings().gemini_embedding_model):
            return embed_model.embed_query(summary_text)

    vector = _run_phase("embed_summary", embed_summary)
    _run_phase("ensure_collection", _ensure_collection)

    from qdrant_client.models import PointStruct

    def persist_summary():
        return _qdrant().upsert(
            collection_name=_COLLECTION,
            points=[
                PointStruct(
                    # O id inclui o user_id: sessões de usuários diferentes nunca compartilham o ponto.
                    id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{user_id}:{session_id}")),
                    vector=vector,
                    payload={"user_id": user_id, "session_id": session_id, "summary": summary_text},
                )
            ],
        )

    _run_phase("persist_summary", persist_summary)


def search_memory(user_id: int, query: str, top_k: int = 3) -> list[str]:
    """Busca semântica nas memórias do usuário. Retorna lista de resumos."""
    try:
        # Uma consulta nunca cria nem recria coleções existentes.
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        embed_model = _run_phase("create_embeddings", _embed_model)

        def embed_query():
            with embedding_call(get_settings().gemini_embedding_model):
                return embed_model.embed_query(query)

        vector = _run_phase("embed_query", embed_query)
        client = _run_phase("create_client", _qdrant)
        response = _run_phase(
            "search",
            lambda: client.query_points(
                collection_name=_COLLECTION,
                query=vector,
                query_filter=Filter(
                    must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))]
                ),
                limit=top_k,
            ),
        )
        return [r.payload.get("summary", "") for r in response.points if r.payload]
    except Exception as error:
        if trace := current_trace():
            trace.error(
                "long_term_memory",
                error,
                operation="search_memory",
                metadata={"phase": "search_memory"},
            )
        return []


def close_session(session_id: str, user_id: int) -> None:
    """Encerra a sessão: lê histórico MongoDB e salva resumo no Qdrant."""
    messages = _run_phase(
        "load_session_history",
        lambda: load_history_validated(user_id, session_id),
    )
    _run_phase("save_session_summary", lambda: save_summary(user_id, session_id, messages))
