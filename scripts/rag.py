"""Inspeciona, indexa e consulta a base documental sem executar o chatbot."""

import argparse
from dataclasses import asdict
import json
import sys

from app.config import ConfigurationError
from app.services.rag import (
    create_embeddings, create_qdrant, index_document, load_document, search_document,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("inspect", "index", "search"))
    parser.add_argument("document", help="Caminho explícito do Markdown UTF-8")
    parser.add_argument("--source", default="delta-product-reference")
    parser.add_argument("--question")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--score-threshold", type=float)
    args = parser.parse_args()
    if args.action == "search" and not (args.question and args.question.strip()):
        parser.error("search exige --question")
    client = None
    try:
        document = load_document(args.document, source=args.source)
        if args.action == "inspect":
            result = asdict(document)
        else:
            embeddings = create_embeddings()
            client = create_qdrant()
            if args.action == "index":
                result = {"indexed_chunks": index_document(document, client=client, embeddings=embeddings),
                          "revision": document.revision}
            else:
                result = search_document(document, args.question, client=client, embeddings=embeddings,
                                         top_k=args.top_k, score_threshold=args.score_threshold)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except ConfigurationError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:
        # Não imprime mensagens externas que podem conter credenciais/URIs.
        print("Falha no RAG. Confira arquivo, configuração, indexação e disponibilidade dos provedores.", file=sys.stderr)
        return 1
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
