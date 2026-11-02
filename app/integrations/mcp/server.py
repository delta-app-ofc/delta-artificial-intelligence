"""Servidor MCP restrito a fontes públicas; execute com python -m deste módulo."""

from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from app.integrations.mcp.sources import ExternalSourceError, list_sources, read_source


server = MCPServer("delta-external-knowledge", log_level="WARNING")
_READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=True)


@server.tool(annotations=_READ_ONLY, structured_output=True)
def list_knowledge_sources() -> dict[str, Any]:
    """Lista fontes públicas de conhecimento sobre água disponíveis para leitura."""
    return {"sources": list_sources()}


@server.tool(annotations=_READ_ONLY, structured_output=True)
def read_knowledge_source(source_id: str) -> dict[str, Any]:
    """Retorna texto e proveniência de uma fonte cadastrada; não aceita URLs livres."""
    try:
        return {"status": "ok", "document": read_source(source_id).model_dump()}
    except ExternalSourceError:
        return {"status": "unavailable", "message": "Fonte externa indisponível."}


if __name__ == "__main__":
    server.run(transport="stdio")
