"""Projeta custo e ROI para 100 e 1000 usuários semanais.

Uso: python -m scripts.cost_projection [--pdf NOME]

Usa só o custo medido nas requisições registradas; sem requisições, não há projeção
(nada é estimado). O PDF é salvo em relatorios/NOME.pdf.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re

from app.observability.metrics import load_records, project, summarize
from app.observability.report import build_pdf

REPORTS_DIR = Path("relatorios")


def pdf_path(name: str) -> Path:
    """Aceita só um nome simples: o arquivo sempre fica dentro de relatorios/."""
    stem = re.sub(r"[^A-Za-z0-9_-]", "", Path(name).stem)
    if not stem:
        raise ValueError("Informe um nome de arquivo com letras, números, - ou _.")
    return REPORTS_DIR / f"{stem}.pdf"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", help="nome do relatório em PDF (salvo em relatorios/NOME.pdf)")
    args = parser.parse_args()
    target = pdf_path(args.pdf) if args.pdf else None

    records = load_records()
    if not records:
        raise SystemExit("Sem requisições registradas: não há custo medido, então não há projeção.")
    summary = summarize(records)
    rows = project(summary)

    print(f"Requisições medidas: {summary['requests']} (em {summary['observed_days']} dia(s))")
    print(f"Custo médio por pergunta: US$ {summary['cost_per_request_usd']}")
    print(f"Taxa de resolução: {summary['resolution_rate'] * 100:.1f}%\n")
    print("| Cenário | Usuários/sem. | Perguntas/sem. | Custo/sem. (US$) | Custo/mês (US$) | Custo/resolução | ROI |")
    print("|---|---|---|---|---|---|---|")
    for row in rows:
        print(f"| {row['scenario']} | {row['users_per_week']} | {row['requests_per_week'] or 'n/d'} | "
              f"{row['cost_week_usd'] or 'n/d'} | {row['cost_month_usd'] or 'n/d'} | "
              f"{row['cost_per_resolution_usd'] or 'n/d'} | {row['roi'] or 'n/d'} |")

    if target:
        REPORTS_DIR.mkdir(exist_ok=True)
        target.write_bytes(build_pdf(summary))
        print(f"\nPDF salvo em {target}")


if __name__ == "__main__":
    main()
