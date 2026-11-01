"""Recupera conhecimento público via MCP, mantendo a proveniência até o Juiz."""

from typing import Annotated

from langchain_core.tools import tool
from pydantic import Field

from app.config import get_settings, validate_mcp_config
from app.integrations.mcp.sources import SOURCES
from app.observability.diagnostics import current_trace
from app.services.rag import create_embeddings, create_qdrant
from app.services.external_knowledge import load_active_sources, search_active_sources
from app.tools.rag import _run_phase


def build_external_knowledge_tool(access_kind: str | None):
    """Vincula as fontes ao perfil confiável; organizational representa o perfil comercial."""
    @tool
    def search_external_knowledge(
        question: Annotated[str, Field(min_length=1, max_length=2000)],
        top_k: Annotated[int, Field(ge=1, le=20)] = 3,
        topic: str | None = None,
        source_id: str | None = None,
    ) -> dict:
        """Busca orientações gerais em fontes públicas previamente atualizadas via MCP.

        Temas: water_conservation e commercial_efficiency. Fontes propostas no handbook:
        midr-water-conservation (geral), epa-residential-saving (residencial) e
        epa-commercial-facilities (comercial). O perfil é vinculado pelo backend;
        o modelo não pode mudá-lo. Os filtros são exatos e opcionais.
        Retorna trechos com URL, título, publicação, coleta, revisão e citation.
        As linhas referem-se ao texto extraído normalizado. Não consulta dados da conta,
        clima atual ou regras do Delta. As páginas não são fontes de tarifas vigentes.
        Não recomende produtos, selos, programas ou campanhas WaterSense; aproveite
        apenas práticas gerais e cite a URL original da EPA para rastreabilidade.
        unavailable indica falha; insufficient_data indica filtro/busca sem resultados.
        """
        settings = get_settings()
        try:
            validate_mcp_config(settings=settings)
            if not settings.mcp_external_enabled:
                return {"status": "unavailable", "chunks": [], "message": "Consulta externa desabilitada."}
            selected = [source for source in SOURCES.values()
                        if (access_kind in source.audiences if access_kind is not None
                            else set(source.audiences) == {"residential", "organizational"})
                        and (topic is None or source.topic == topic)
                        and (source_id is None or source.id == source_id)]
            if not selected or not question.strip():
                return {"status": "insufficient_data", "chunks": []}
            if not settings.gemini_api_key or not settings.gemini_embedding_model or not settings.qdrant_url:
                return {"status": "unavailable", "chunks": [], "message": "Base externa não configurada."}

            client = _run_phase("external_client", create_qdrant)
            active = load_active_sources([source.id for source in selected], client=client)
            failures = [source.id for source in selected if source.id not in {s["source_id"] for s in active}]
            if not active:
                return {"status": "unavailable", "chunks": [], "unavailable_sources": failures,
                        "message": "As fontes externas ainda não possuem uma revisão completa dentro da validade."}
            embeddings = _run_phase("external_embeddings", create_embeddings)
            results = search_active_sources(active, question, client=client, embeddings=embeddings, top_k=top_k)
            chunks = []
            for result in sorted(results, key=lambda item: item["score"], reverse=True)[:top_k]:
                citation = f"[{result['title']}]({result['url']})"
                chunks.append({**result, "citation": citation})
            return {"status": "ok" if chunks else "unavailable" if failures else "insufficient_data",
                    "chunks": chunks, "unavailable_sources": failures}
        except Exception as error:
            if trace := current_trace():
                trace.error("mcp_external", error, operation="search_external_knowledge")
            return {"status": "unavailable", "chunks": [],
                    "message": "Não foi possível consultar a base externa neste momento."}

    return search_external_knowledge


# Chamadas sem perfil usam somente a fonte geral, nunca uma fonte exclusiva.
search_external_knowledge = build_external_knowledge_tool(None)
