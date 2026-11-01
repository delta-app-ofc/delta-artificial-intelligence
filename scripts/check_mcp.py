"""Valida o MCP real e a fonte pública, sem LLM, Qdrant ou dados da conta."""

import argparse
import asyncio
import json

from app.config import get_settings, validate_mcp_config
from app.integrations.mcp.client import call_source
from app.integrations.mcp.sources import SOURCES


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-id", choices=sorted(SOURCES), default=next(iter(SOURCES)))
    arguments = parser.parse_args()
    try:
        settings = get_settings()
        validate_mcp_config(settings=settings)
        # A execução explícita deste diagnóstico independe da habilitação no chatbot.
        document = asyncio.run(call_source(arguments.source_id, settings.mcp_timeout_seconds))
    except Exception:
        print(json.dumps({"status": "unavailable", "message": "Falha ao consultar MCP/fonte pública."},
                         ensure_ascii=False))
        return 1
    print(json.dumps({"status": "ok", "source_id": document.source_id, "url": document.url,
                      "published_at": document.published_at, "collected_at": document.collected_at,
                      "revision": document.revision, "characters": len(document.text)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
