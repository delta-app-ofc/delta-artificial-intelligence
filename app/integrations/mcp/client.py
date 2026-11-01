"""Cliente stdio: chama somente o servidor deste projeto, sem comandos vindos do LLM."""

import asyncio
import sys
from threading import Lock
from time import monotonic

import anyio
from mcp import Client, StdioServerParameters

from app.config import BASE_DIR, get_settings, validate_mcp_config
from app.integrations.mcp.sources import ExternalDocument, ExternalSourceError, SOURCES
from app.observability.diagnostics import component


_CACHE: dict[str, tuple[float, ExternalDocument]] = {}
_CACHE_LOCK = Lock()
_FETCH_LOCK = Lock()


def server_parameters() -> StdioServerParameters:
    """O SDK herda apenas variáveis básicas do SO; não repassa credenciais do backend."""
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.integrations.mcp.server"],
        cwd=BASE_DIR,
        env={"PYTHONUTF8": "1"},
    )


async def call_source(source_id: str, timeout: float) -> ExternalDocument:
    """Aplica prazo total incluindo inicialização, chamada e liberação do subprocesso."""
    try:
        with anyio.fail_after(timeout):
            async with Client(server_parameters(), read_timeout_seconds=timeout) as client:
                response = await client.call_tool("read_knowledge_source", {"source_id": source_id})
                data = response.structured_content
                if response.is_error or not isinstance(data, dict) or data.get("status") != "ok":
                    raise ExternalSourceError("Fonte MCP indisponível.")
                document = ExternalDocument.model_validate(data.get("document"))
                if document.source_id != source_id:
                    raise ExternalSourceError("O MCP retornou uma fonte diferente da solicitada.")
                return document
    except Exception as error:
        # Nunca inclua stderr, mensagens do SDK ou valores de ambiente na resposta pública.
        raise ExternalSourceError("Não foi possível consultar a fonte via MCP.") from error


def _fetch_source(source_id: str) -> ExternalDocument:
    """Cache limitado ao catálogo e ao TTL; falhas não são gravadas nem usam cópia vencida."""
    settings = get_settings()
    validate_mcp_config(settings=settings)
    if not settings.mcp_external_enabled:
        raise ExternalSourceError("Consulta externa desabilitada.")
    if source_id not in SOURCES:
        raise ExternalSourceError("Fonte externa desconhecida.")
    with _CACHE_LOCK:
        cached = _CACHE.get(source_id)
        if cached and monotonic() - cached[0] < settings.mcp_cache_ttl_seconds:
            return cached[1]
    document = asyncio.run(call_source(source_id, settings.mcp_timeout_seconds))
    with _CACHE_LOCK:
        _CACHE[source_id] = (monotonic(), document)
    return document


def fetch_source(source_id: str) -> ExternalDocument:
    """Uma coleta por vez no processo; chamadas concorrentes reutilizam o cache."""
    with _FETCH_LOCK:
        return _fetch_source(source_id)


async def call_sources(source_ids: list[str], timeout: float) -> dict:
    """Abre uma sessão por lote, com no máximo as três fontes do catálogo."""
    from contextlib import AsyncExitStack
    try:
        with anyio.fail_after(timeout):
            async with AsyncExitStack() as stack:
                with component("rag_mcp_connect"):
                    client = await stack.enter_async_context(
                        Client(server_parameters(), read_timeout_seconds=timeout))

                async def read(source_id):
                    try:
                        with component("rag_mcp_read"):
                            response = await client.call_tool("read_knowledge_source", {"source_id": source_id})
                            data = response.structured_content
                            if response.is_error or not isinstance(data, dict) or data.get("status") != "ok":
                                raise ExternalSourceError("Fonte MCP indisponível.")
                            document = ExternalDocument.model_validate(data.get("document"))
                            if document.source_id != source_id:
                                raise ExternalSourceError("Fonte MCP divergente.")
                            return document
                    except Exception:
                        return None

                documents = await asyncio.gather(*(read(source_id) for source_id in source_ids))
                return dict(zip(source_ids, documents))
    except Exception as error:
        raise ExternalSourceError("Não foi possível atualizar as fontes via MCP.") from error


def fetch_sources(source_ids: list[str], *, force: bool = False) -> dict:
    """Cache e exclusão de coletas duplicadas também para atualizações em lote."""
    settings = get_settings()
    validate_mcp_config(settings=settings)
    if not settings.mcp_external_enabled or not source_ids or any(s not in SOURCES for s in source_ids):
        raise ExternalSourceError("Consulta externa desabilitada ou fonte desconhecida.")
    source_ids = list(dict.fromkeys(source_ids))
    with _FETCH_LOCK:
        with _CACHE_LOCK:
            result = {s: _CACHE[s][1] for s in source_ids if not force and s in _CACHE
                      and monotonic() - _CACHE[s][0] < settings.mcp_cache_ttl_seconds}
        missing = [s for s in source_ids if s not in result]
        if missing:
            documents = asyncio.run(call_sources(missing, settings.mcp_timeout_seconds))
            with _CACHE_LOCK:
                for source_id, document in documents.items():
                    if document is not None:
                        _CACHE[source_id] = (monotonic(), document)
            result.update(documents)
        return result


def clear_source_cache() -> None:
    """Descarta textos públicos em memória, por exemplo ao trocar configuração."""
    with _CACHE_LOCK:
        _CACHE.clear()
