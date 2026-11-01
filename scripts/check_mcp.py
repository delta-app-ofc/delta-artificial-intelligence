"""Valida o MCP real e a fonte pública, sem LLM, Qdrant ou dados da conta."""

import argparse
import asyncio
import json

from app.config import get_settings, validate_mcp_config
from app.integrations.mcp.client import call_source
from app.integrations.mcp.sources import SOURCES


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--source-id", choices=sorted(SOURCES), default=next(iter(SOURCES)))
    group.add_argument("--all", action="store_true", help="Verifica cada fonte do catálogo aprovado.")
    arguments = parser.parse_args()
    try:
        settings = get_settings()
        validate_mcp_config(settings=settings)
        # A execução explícita deste diagnóstico independe da habilitação no chatbot.
    except Exception:
        print(json.dumps({"status": "unavailable", "message": "Configuração MCP inválida."}, ensure_ascii=False))
        return 1
    failures = 0
    for source_id in SOURCES if arguments.all else [arguments.source_id]:
        try:
            document = asyncio.run(call_source(source_id, settings.mcp_timeout_seconds))
        except Exception:
            failures += 1
            print(json.dumps({"status": "unavailable", "source_id": source_id,
                              "message": "Falha ao consultar MCP/fonte pública."}, ensure_ascii=False), flush=True)
            continue
        print(json.dumps({"status": "ok", "source_id": document.source_id, "url": document.url,
                          "audiences": document.audiences, "language": document.language,
                          "published_at": document.published_at, "collected_at": document.collected_at,
                          "revision": document.revision, "characters": len(document.text)}, ensure_ascii=False), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
