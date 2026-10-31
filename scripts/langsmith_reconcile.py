"""Compara o custo calculado pelo Delta com o custo registrado no LangSmith.

Uso: python -m scripts.langsmith_reconcile [--limit 50]

Lê os runs raiz do projeto LANGSMITH_PROJECT (a chave vem do .env, nunca é impressa)
e mostra tokens, custo e latência do LangSmith ao lado do cálculo local.
"""
from __future__ import annotations

import argparse

from app.config import get_observability_config
from app.observability.langsmith import enable_langsmith
from app.observability.metrics import load_records, summarize


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    if not enable_langsmith():
        raise SystemExit("LangSmith desligado: defina LANGSMITH_TRACING=true e LANGSMITH_API_KEY no .env.")

    from langsmith import Client

    project = get_observability_config().langsmith_project
    runs = list(Client().list_runs(project_name=project, is_root=True, limit=args.limit))
    tokens = sum(run.total_tokens or 0 for run in runs)
    cost = sum(float(run.total_cost or 0) for run in runs)
    latencies = [(run.end_time - run.start_time).total_seconds() * 1000 for run in runs if run.end_time]

    local = summarize(load_records(args.limit))
    print(f"Projeto LangSmith: {project} · {len(runs)} runs raiz")
    print(f"LangSmith: {tokens} tokens · US$ {cost:.6f} · latência média "
          f"{sum(latencies) / len(latencies):.0f} ms" if latencies else f"LangSmith: {tokens} tokens · US$ {cost:.6f}")
    print(f"Delta:     {local['tokens']['input'] + local['tokens']['output']} tokens · "
          f"US$ {local['cost_usd']} · latência média {local['latency_total_ms']['avg']} ms")
    print("Diferenças pequenas são esperadas: tabelas de preço e janelas de requisições diferem.")


if __name__ == "__main__":
    main()
