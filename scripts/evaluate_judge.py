"""Avalia o Juiz com casos de evidência versionados e um provedor real, sem bancos."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter
from typing import Any

from app.agents.judge import JudgeAgent, JudgeInput
from app.observability.diagnostics import Trace, capture

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals/datasets/judge.json"


def evaluate_cases(cases: list[dict[str, Any]], classifier: Any | None = None) -> dict:
    """Executa casos e separa erro do provedor de erro de qualidade."""
    rows = []
    for case in cases:
        trace = Trace("judge_eval", user_id=12)
        started = perf_counter()
        with capture(trace):
            result = JudgeAgent(classifier=classifier).run(JudgeInput(
                question=case["question"], candidate=case["candidate"],
                agent_results=case["agent_results"],
            ))
        evaluated = result.status == "evaluated" and not trace.errors
        decision_passed = result.decision == case["expected_decision"]
        severity_passed = result.severity == case["expected_severity"]
        rows.append({
            "id": case["id"], "expected_decision": case["expected_decision"],
            "actual_decision": result.decision, "expected_severity": case["expected_severity"],
            "actual_severity": result.severity, "status": result.status,
            "evaluated": evaluated, "passed": evaluated and decision_passed and severity_passed,
            "duration_ms": round((perf_counter() - started) * 1000, 1),
            "reason_codes": result.reason_codes, "error_count": len(trace.errors),
        })
    evaluated_rows = [row for row in rows if row["evaluated"]]
    return {
        "mode": "live_judge", "product_database_access": False, "results": rows,
        "metrics": {
            "total": len(rows), "evaluated": len(evaluated_rows),
            "passed": sum(row["passed"] for row in rows),
            "decision_accuracy": sum(row["passed"] for row in rows) / len(evaluated_rows) if evaluated_rows else None,
            "unavailable": sum(not row["evaluated"] for row in rows),
        },
        "passed": bool(rows) and all(row["passed"] for row in rows),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--output", type=Path, default=ROOT / "reports/judge-live.json")
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
