"""Atualiza e ativa fontes externas sem executar chat, roteador ou Juiz."""

import asyncio
import json

from app.observability.embedding_usage import close_usage_clients
from app.services.external_knowledge import refresh_with_diagnostics
from app.services.rag import close_rag_clients


def main():
    try:
        result = refresh_with_diagnostics()
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["status"] == "ok" else 1
    except Exception as error:
        print(json.dumps({"status": "unavailable", "error_type": type(error).__name__}))
        return 1
    finally:
        close_usage_clients()
        asyncio.run(close_rag_clients())


if __name__ == "__main__":
    raise SystemExit(main())
