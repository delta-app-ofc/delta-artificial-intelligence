"""Projeta custo e ROI para 100 e 1000 usuários semanais.

Uso: python -m scripts.cost_projection [--pdf relatorio.pdf]

Usa o custo médio real das requisições registradas. Sem registros, usa uma
estimativa (tokens por pergunta abaixo) e avisa que é premissa.
"""
from __future__ import annotations

import argparse

from app.observability.metrics import load_records, model_cost, project, summarize
from app.observability.report import build_pdf

# Estimativa sem dados reais: uma pergunta com ~2 chamadas ao modelo principal.
ASSUMED_MODEL = "gpt-6-luna"
ASSUMED_INPUT_TOKENS = 6000
ASSUMED_OUTPUT_TOKENS = 1200
ASSUMED_RESOLUTION_RATE = 0.85


def assumed_summary() -> dict:
    cost = model_cost(ASSUMED_MODEL, ASSUMED_INPUT_TOKENS, ASSUMED_OUTPUT_TOKENS)
    summary = summarize([])
    summary.update(cost_per_request_usd=cost, resolution_rate=ASSUMED_RESOLUTION_RATE)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", help="caminho para salvar o relatório em PDF")
    args = parser.parse_args()

    records = load_records()
    summary = summarize(records)
    if not records:
        print("Sem requisições registradas: usando estimativa (premissa), não medição.\n")
        summary = assumed_summary()
    rows = project(summary)

    print(f"Custo médio por pergunta: US$ {summary['cost_per_request_usd']}")
    print(f"Taxa de resolução: {summary['resolution_rate'] * 100:.1f}%\n")
    print("| Cenário | Usuários/sem. | Perguntas/sem. | Custo/sem. (US$) | Custo/mês (US$) | Custo/resolução | ROI |")
    print("|---|---|---|---|---|---|---|")
    for row in rows:
        print(f"| {row['scenario']} | {row['users_per_week']} | {row['requests_per_week']} | "
              f"{row['cost_week_usd']} | {row['cost_month_usd']} | {row['cost_per_resolution_usd']} | {row['roi']} |")

    if args.pdf:
        with open(args.pdf, "wb") as file:
            file.write(build_pdf(summary))
        print(f"\nPDF salvo em {args.pdf}")


if __name__ == "__main__":
    main()
