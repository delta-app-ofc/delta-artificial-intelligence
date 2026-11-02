"""Atualiza o índice documental quando necessário e consulta a base oficial do Delta."""

import logging
from time import perf_counter
from typing import Annotated, Callable, TypeVar

from langchain_core.tools import tool
from pydantic import Field

from app.config import get_settings
from app.observability.diagnostics import component, current_trace, public_data
from app.services.rag import (
    create_embeddings, create_qdrant, ensure_document_indexed, load_document, search_document,
)

logger = logging.getLogger(__name__)
_T = TypeVar("_T")


def _run_phase(phase: str, action: Callable[[], _T]) -> _T:
    trace = current_trace()
    component_name = f"rag_{phase}"
    started = perf_counter()
    if trace:
        trace.event(
            "rag.phase.start",
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
                        operation="search_knowledge_base",
                        metadata={"phase": phase, "tool": "search_knowledge_base"},
                    )
                raise
    except Exception as error:
        record = None
        if trace:
            record = trace.error(
                component_name,
                error,
                operation="search_knowledge_base",
                metadata={"phase": phase, "tool": "search_knowledge_base"},
            )
            trace.event(
                "rag.phase.end",
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
            "rag.phase.end",
            component=component_name,
            operation=phase,
            status="success",
            duration_ms=round((perf_counter() - started) * 1000, 1),
            metadata={"phase": phase, "outcome": "completed"},
        )
    return result


@tool
def search_knowledge_base(
    question: Annotated[str, Field(min_length=1, max_length=2000)],
    top_k: Annotated[int, Field(ge=1, le=20)] = 3,
) -> dict:
    """Busca explicações sobre o produto Delta na documentação oficial.

    Use para dúvidas de cadastro, vínculo de equipamento, indicadores, metas,
    alertas e demais regras do produto. Prepara automaticamente a revisão
    configurada quando necessário. Não retorna nem altera registros pessoais da conta.
    A saída contém trechos, capítulos, linhas e referências para citar. Status
    unavailable indica falha de acesso; insufficient_data indica busca sem
    trechos. Nenhum desses estados autoriza completar com conhecimento geral.
    """
    settings = _run_phase("configuration", get_settings)
    if (
        not settings.gemini_api_key
        or not settings.gemini_embedding_model
        or not settings.qdrant_url
        or not settings.rag_document_path
    ):
        if trace := current_trace():
            trace.event(
                "rag.unavailable",
                component="rag",
                operation="configuration",
                status="unavailable",
                metadata={"phase": "configuration", "outcome": "missing_configuration"},
            )
        return {
            "status": "unavailable",
            "message": (
                "Configure GEMINI_API_KEY, GEMINI_EMBEDDING_MODEL, QDRANT_URL "
                "e RAG_DOCUMENT_PATH para consultar a base."
            ),
            "chunks": [],
        }

    phase = "load_document"
    try:
        document = _run_phase("load_document", load_document)
        phase = "create_client"
        client = _run_phase("create_client", create_qdrant)
        phase = "create_embeddings"
        embeddings = _run_phase("create_embeddings", create_embeddings)
        phase = "ensure_index"
        _run_phase(
            "ensure_index",
            lambda: ensure_document_indexed(document, client=client, embeddings=embeddings),
        )
        phase = "search"
        results = _run_phase(
            "search",
            lambda: search_document(
                document, question, client=client, embeddings=embeddings, top_k=top_k,
            ),
        )
        phase = "format_results"

        def format_chunks() -> list[dict]:
            chunks = []
            for result in results:
                location = " > ".join(result["headings"])
                citation = (
                    f"{result['source']} > {location} "
                    f"(revisão {result['revision']}; linhas {result['start_line']}-{result['end_line']})"
                )
                chunks.append({**result, "citation": citation})
            return chunks

        chunks = _run_phase("format_results", format_chunks)
        return {
            "status": "ok" if chunks else "insufficient_data",
            "chunks": chunks,
        }
    except Exception as error:
        detail = " ".join(public_data(str(error)).split())
        logger.error(
            "Falha no RAG durante %s (%s): %s",
            phase,
            type(error).__name__,
            detail or "sem detalhes fornecidos pela integração",
        )
        return {
            "status": "unavailable",
            "message": (
                "Não foi possível preparar ou consultar a base documental "
                "do Delta neste momento."
            ),
            "chunks": [],
        }
