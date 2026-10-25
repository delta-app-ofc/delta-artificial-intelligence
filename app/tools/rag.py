"""Consulta a base oficial do Delta já indexada no Qdrant."""

import hashlib
from pathlib import Path

from langchain_core.tools import tool
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue

from app.config import BASE_DIR, get_settings


COLLECTION = "rag_documents"
SOURCE = "delta-product-reference"


@tool
def search_knowledge_base(question: str) -> dict:
    """Busca explicações sobre o produto Delta na documentação oficial.

    Use para dúvidas de cadastro, vínculo de equipamento, indicadores, metas,
    alertas e demais regras do produto. Não retorna registros pessoais da conta.
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

    try:
        # O payload da indexação identifica o modelo com o prefixo models/.
        embedding_model = (
            "models/" + settings.gemini_embedding_model.removeprefix("models/")
        )

        path = Path(settings.rag_document_path)
        if not path.is_absolute():
            path = BASE_DIR / path

        document = path.read_text(encoding="utf-8-sig")
        # Mesma identificação usada na indexação Markdown existente.
        revision = hashlib.sha256(
            ("markdown-headings-v2\n" + document).encode("utf-8")
        ).hexdigest()

        client = QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            timeout=30,
        )

        if not client.collection_exists(COLLECTION):
            return {
                "status": "unavailable",
                "message": (
                    "A coleção rag_documents precisa existir e estar indexada "
                    "antes da consulta."
                ),
                "chunks": [],
            }

        query_filter = Filter(must=[
            FieldCondition(key=key, match=MatchValue(value=value))
            for key, value in {
                "source": SOURCE,
                "revision": revision,
                "embedding_model": embedding_model,
            }.items()
        ])

        if client.count(COLLECTION, count_filter=query_filter, exact=True).count == 0:
            return {
                "status": "unavailable",
                "message": (
                    "A revisão atual do documento ainda não está indexada "
                    "com o modelo de embedding configurado na base RAG."
                ),
                "chunks": [],
            }

        embeddings = GoogleGenerativeAIEmbeddings(
            model=embedding_model,
            api_key=settings.gemini_api_key,
            output_dimensionality=3072,
            vertexai=False,
            client_args={"timeout": 30},
        )
        vector = embeddings.embed_query(question, task_type="RETRIEVAL_QUERY")
        result = client.query_points(
            COLLECTION,
            query=vector,
            query_filter=query_filter,
            limit=3,
            with_payload=True,
        )

        chunks = []

        for point in result.points:
            payload = point.payload or {}
            if not payload.get("text"):
                continue

            location = " > ".join(payload["headings"])
            citation = f"{location} (linhas {payload['start_line']}-{payload['end_line']})"
            chunks.append({
                "id": str(point.id),
                "text": payload["text"],
                "headings": payload["headings"],
                "source": SOURCE,
                "revision": revision,
                "start_line": payload["start_line"],
                "end_line": payload["end_line"],
                "score": point.score,
                "citation": citation,
            })

        return {
            "status": "ok" if chunks else "insufficient_data",
            "chunks": chunks,
        }

    except Exception:
        return {
            "status": "unavailable",
            "message": "Não foi possível consultar a base documental do Delta neste momento.",
            "chunks": [],
        }

    finally:
        if client is not None:
            client.close()
