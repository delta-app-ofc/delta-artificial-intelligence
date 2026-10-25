"""Atualiza o índice documental quando necessário e consulta a base oficial do Delta."""

import logging

from langchain_core.tools import tool

from app.config import get_settings
from app.observability.diagnostics import current_trace, public_data
from app.services.rag import (
    create_embeddings, create_qdrant, ensure_document_indexed, load_document, search_document,
)

logger = logging.getLogger(__name__)


@tool
def search_knowledge_base(question: str) -> dict:
    """Busca explicações sobre o produto Delta na documentação oficial.

    Use para dúvidas de cadastro, vínculo de equipamento, indicadores, metas,
    alertas e demais regras do produto. Prepara automaticamente a revisão
    configurada quando necessário. Não retorna nem altera registros pessoais da conta.
    A saída contém trechos, capítulos, linhas e referências para citar. Status
    unavailable indica falha de acesso; insufficient_data indica busca sem
    trechos. Nenhum desses estados autoriza completar com conhecimento geral.
    """
    settings = get_settings()
    if (
        not settings.gemini_api_key
        or not settings.gemini_embedding_model
        or not settings.qdrant_url
        or not settings.rag_document_path
    ):
        return {
            "status": "unavailable",
            "message": (
                "Configure GEMINI_API_KEY, GEMINI_EMBEDDING_MODEL, QDRANT_URL "
                "e RAG_DOCUMENT_PATH para consultar a base."
            ),
            "chunks": [],
        }

    client = None
    phase = "leitura do documento"
    try:
        document = load_document()
        phase = "conexão com Qdrant"
        client = create_qdrant()
        phase = "criação do modelo de embeddings"
        embeddings = create_embeddings()
        phase = "preparação do índice documental"
        ensure_document_indexed(document, client=client, embeddings=embeddings)
        phase = "busca de trechos"
        results = search_document(
            document, question, client=client, embeddings=embeddings,
        )
        chunks = []
        for result in results:
            location = " > ".join(result["headings"])
            citation = f"{location} (linhas {result['start_line']}-{result['end_line']})"
            chunks.append({**result, "citation": citation})

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
        if trace := current_trace():
            trace.error("rag", error)
        return {
            "status": "unavailable",
            "message": (
                "Não foi possível preparar ou consultar a base documental "
                "do Delta neste momento."
            ),
            "chunks": [],
        }
    finally:
        if client is not None:
            client.close()
