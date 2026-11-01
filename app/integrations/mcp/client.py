"""Cliente stdio: chama somente o servidor deste projeto, sem comandos vindos do LLM."""

import asyncio
import sys
from threading import Lock
from time import monotonic

import anyio
from mcp import Client, StdioServerParameters

from app.config import BASE_DIR, get_settings, validate_mcp_config
from app.integrations.mcp.sources import ExternalDocument, ExternalSourceError, SOURCES


_CACHE: dict[str, tuple[float, ExternalDocument]] = {}
_CACHE_LOCK = Lock()


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


def fetch_source(source_id: str) -> ExternalDocument:
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


def clear_source_cache() -> None:
    """Descarta textos públicos em memória, por exemplo ao trocar configuração."""
    with _CACHE_LOCK:
        _CACHE.clear()
