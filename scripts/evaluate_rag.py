"""Avalia recuperação RAG por hit@k e MRR, com consulta real opt-in e sem bancos de produto."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

from app.observability.diagnostics import Trace, capture
from app.tools.rag import search_knowledge_base

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals/datasets/rag.json"


def _ranked_headings(result: dict) -> list[str]:
    return [" > ".join(chunk.get("headings", [])) for chunk in result.get("chunks", [])]


def evaluate_cases(cases: list[dict], search=search_knowledge_base.invoke) -> dict:
    """Calcula hit@k e reciprocal rank sem considerar indisponibilidade como acerto."""
    rows = []
    for case in cases:
        trace = Trace("rag_eval", user_id=12)
        started = perf_counter()
        with capture(trace):
            result = search({"question": case["question"], "top_k": 3})
        headings = _ranked_headings(result)
        position = next((index + 1 for index, heading in enumerate(headings)
                         if case["expected_heading"] in heading), None)
        evaluated = result.get("status") == "ok" and not trace.errors
        rows.append({
            "id": case["id"], "expected_heading": case["expected_heading"],
            "retrieved_headings": headings, "rank": position,
            "evaluated": evaluated, "hit_at_1": evaluated and position == 1,
            "hit_at_3": evaluated and position is not None,
            "reciprocal_rank": (1 / position) if evaluated and position else 0.0,
            "duration_ms": round((perf_counter() - started) * 1000, 1),
            "error_count": len(trace.errors),
        })
    evaluated_rows = [row for row in rows if row["evaluated"]]
    return {
        "mode": "live_rag", "product_database_access": False, "results": rows,
        "metrics": {
            "total": len(rows), "evaluated": len(evaluated_rows),
            "unavailable": sum(not row["evaluated"] for row in rows),
            "hit_at_1": sum(row["hit_at_1"] for row in evaluated_rows) / len(evaluated_rows) if evaluated_rows else None,
            "hit_at_3": sum(row["hit_at_3"] for row in evaluated_rows) / len(evaluated_rows) if evaluated_rows else None,
            "mrr": sum(row["reciprocal_rank"] for row in evaluated_rows) / len(evaluated_rows) if evaluated_rows else None,
        },
        "passed": bool(evaluated_rows) and all(row["evaluated"] for row in rows),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--output", type=Path, default=ROOT / "reports/rag-live.json")
    args = parser.parse_args(argv)
    if not args.allow_live or not 1 <= args.limit <= 20:
        parser.error("Use --allow-live e --limit entre 1 e 20; esta avaliação pode consumir créditos.")
    cases = json.loads(DATASET.read_text(encoding="utf-8"))[:args.limit]
    report = evaluate_cases(cases)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["metrics"], ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
