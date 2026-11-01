"""Recupera conhecimento público via MCP, mantendo a proveniência até o Juiz."""

from typing import Annotated

from langchain_core.tools import tool
from pydantic import Field

from app.config import get_settings, validate_mcp_config
from app.integrations.mcp.client import fetch_source
from app.integrations.mcp.sources import SOURCES
from app.observability.diagnostics import current_trace
from app.services.rag import (
    create_embeddings, create_qdrant, ensure_document_indexed, external_document, search_document,
)
from app.tools.rag import _run_phase


@tool
def search_external_knowledge(
    question: Annotated[str, Field(min_length=1, max_length=2000)],
    top_k: Annotated[int, Field(ge=1, le=20)] = 3,
    topic: str | None = None,
    source_id: str | None = None,
) -> dict:
    """Busca orientações gerais sobre uso consciente da água em fontes públicas via MCP.

    Use para conservação e eficiência hídrica. Tema disponível: water_conservation.
    Fonte: senado-water-conservation. Os filtros são exatos e opcionais.
    Retorna trechos com URL, título, publicação, coleta, revisão e citation.
    As linhas referem-se ao texto extraído normalizado. Não consulta dados da conta,
    clima atual ou regras do Delta. O artigo é histórico; não comprova condições atuais.
    unavailable indica falha; insufficient_data indica filtro/busca sem resultados.
    """
    settings = get_settings()
    try:
        validate_mcp_config(settings=settings)
        if not settings.mcp_external_enabled:
            return {"status": "unavailable", "chunks": [], "message": "Consulta externa desabilitada."}
        selected = [source for source in SOURCES.values()
                    if (topic is None or source.topic == topic)
                    and (source_id is None or source.id == source_id)]
        if not selected or not question.strip():
            return {"status": "insufficient_data", "chunks": []}
        if not settings.gemini_api_key or not settings.gemini_embedding_model or not settings.qdrant_url:
            return {"status": "unavailable", "chunks": [], "message": "Base externa não configurada."}

        client = _run_phase("external_client", create_qdrant)
        embeddings = _run_phase("external_embeddings", create_embeddings)
        results = []
        failures = []
        for source in selected:
            try:
                snapshot = _run_phase("mcp_fetch", lambda: fetch_source(source.id))
                document = external_document(snapshot)
                _run_phase("external_index", lambda: ensure_document_indexed(
                    document, client=client, embeddings=embeddings,
                ))
                results.extend(_run_phase("external_search", lambda: search_document(
                    document, question, client=client, embeddings=embeddings, top_k=top_k,
                )))
            except Exception:
                failures.append(source.id)
        chunks = []
        for result in sorted(results, key=lambda item: item["score"], reverse=True)[:top_k]:
            citation = (
                f"[{result['title']}]({result['url']}) — publicado em {result['published_at']}; "
                f"coletado em {result['collected_at']}; revisão {result['revision']}; "
                f"linhas {result['start_line']}-{result['end_line']} do texto extraído"
            )
            chunks.append({**result, "citation": citation})
        return {"status": "ok" if chunks else "unavailable" if failures else "insufficient_data",
                "chunks": chunks, "unavailable_sources": failures}
    except Exception as error:
        if trace := current_trace():
            trace.error("mcp_external", error, operation="search_external_knowledge")
        return {"status": "unavailable", "chunks": [],
                "message": "Não foi possível consultar a base externa neste momento."}
