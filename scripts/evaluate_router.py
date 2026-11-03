"""Avalia o roteador com casos versionados e um provedor real, sem acessar bancos."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

from app.graph.router import classify
from app.observability.diagnostics import Trace, capture

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals/datasets/router.json"


def _set_metrics(rows: list[dict]) -> dict:
    expected_pairs = {(agent, row["id"]) for row in rows for agent in row["expected_agents"]}
    predicted_pairs = {(agent, row["id"]) for row in rows for agent in row["predicted_agents"]}
    true_positive = len(expected_pairs & predicted_pairs)
    precision = true_positive / len(predicted_pairs) if predicted_pairs else 1.0
    recall = true_positive / len(expected_pairs) if expected_pairs else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "total": len(rows),
        "evaluated": sum(row["evaluated"] for row in rows),
        "passed": sum(row["passed"] for row in rows),
        "exact_route_accuracy": sum(row["passed"] for row in rows) / len(rows) if rows else None,
        "intent_accuracy": sum(row["intent_passed"] for row in rows) / len(rows) if rows else None,
        "complexity_accuracy": sum(row["complexity_passed"] for row in rows) / len(rows) if rows else None,
        "agent_precision": precision,
        "agent_recall": recall,
        "agent_f1": f1,
        "unavailable": sum(not row["evaluated"] for row in rows),
    }


def evaluate_cases(cases: list[dict]) -> dict:
    """Executa os casos e não conta falhas do provedor como acertos."""
    rows = []
    for case in cases:
        trace = Trace("router_eval", user_id=12)
        started = perf_counter()
        with capture(trace):
            decision = classify(case["question"], {"access_kind": case["access_kind"]})
        predicted_agents = sorted(decision.agents)
        expected_agents = sorted(case["agents"])
        evaluated = not bool(trace.errors)
        intent_passed = decision.intent == case["intent"]
        complexity_passed = decision.complexity == case["complexity"]
        route_passed = predicted_agents == expected_agents
        rows.append({
            "id": case["id"], "expected_agents": expected_agents,
            "predicted_agents": predicted_agents, "expected_intent": case["intent"],
            "predicted_intent": decision.intent, "expected_complexity": case["complexity"],
            "predicted_complexity": decision.complexity, "evaluated": evaluated,
            "intent_passed": evaluated and intent_passed,
            "complexity_passed": evaluated and complexity_passed,
            "passed": evaluated and route_passed and intent_passed and complexity_passed,
            "duration_ms": round((perf_counter() - started) * 1000, 1),
            "error_count": len(trace.errors),
        })
    metrics = _set_metrics(rows)
    return {"mode": "live_router", "product_database_access": False, "results": rows,
            "metrics": metrics, "passed": bool(rows) and all(row["passed"] for row in rows)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--output", type=Path, default=ROOT / "reports/router-live.json")
    args = parser.parse_args(argv)
    if not args.allow_live or not 1 <= args.limit <= 50:
        parser.error("Use --allow-live e --limit entre 1 e 50; esta avaliação pode consumir créditos.")
    cases = json.loads(DATASET.read_text(encoding="utf-8"))[:args.limit]
    report = evaluate_cases(cases)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["metrics"], ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
