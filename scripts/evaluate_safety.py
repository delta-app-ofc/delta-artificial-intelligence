"""Avalia regras de segurança sem banco, credenciais ou chamadas a modelos.

Execute com python -m scripts.evaluate_safety. O relatório registra cada erro;
o gate impede regressões frente às lacunas explicitamente aceitas no baseline.
Isto mede apenas regras determinísticas, não a qualidade semântica da IA.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "evals" / "datasets"


def load_cases(directory: Path) -> dict[str, list[dict]]:
    """Carrega casos e rejeita dados vazios ou com identificadores repetidos."""
    suites = {}
    seen = set()
    for name in ("input_guardrail", "output_pii", "output_ownership"):
        cases = json.loads((directory / f"{name}.json").read_text(encoding="utf-8"))
        if not isinstance(cases, list) or not cases:
            raise ValueError(f"Dataset vazio ou inválido: {name}")
        for case in cases:
            case_id = case["id"]
            if not isinstance(case_id, str) or not case_id or case_id in seen:
                raise ValueError(f"Identificador inválido ou repetido: {case_id}")
            seen.add(case_id)
            if name == "output_pii":
                if not isinstance(case["sensitive"], list) or not all(
                    isinstance(value, str) and value for value in case["sensitive"]
                ):
                    raise ValueError(f"Lista de dados sensíveis inválida: {case_id}")
                if not isinstance(case["expected_response"], str):
                    raise ValueError(f"Resposta esperada inválida: {case_id}")
                text = case["response"]
            else:
                if case["expected"] not in ("block", "allow"):
                    raise ValueError(f"Resultado esperado inválido: {case_id}")
                text = case["text"] if name == "input_guardrail" else case["response"]
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f"Texto vazio ou inválido: {case_id}")
        suites[name] = cases
    return suites


def evaluate(suites: dict[str, list[dict]]) -> dict:
    """Executa as funções públicas usadas pelo aplicativo, sem substituir modelos."""
    from app.guardrails.input import validate_input_rules
    from app.guardrails.output import validate_output, validate_ownership

    results = []
    for name, cases in suites.items():
        for case in cases:
            if name == "input_guardrail" and case.get("layer") == "classifier":
                actual, passed = "not_evaluated_requires_llm", None
            elif name == "input_guardrail":
                actual = "allow" if validate_input_rules(12, case["text"])["ok"] else "block"
                passed = actual == case["expected"]
            elif name == "output_ownership":
                actual = "allow" if validate_ownership(case["response"], case["user_id"])["ok"] else "block"
                passed = actual == case["expected"]
            else:
                output = validate_output(case["response"])
                cleaned = output.get("response", "")
                # Confere redação completa e preservação dos números e pontuação legítimos.
                passed = output["ok"] and cleaned == case["expected_response"]
                actual = "pass" if passed else "fail"
            results.append({"id": case["id"], "suite": name, "passed": passed,
                            "actual": actual, "expected": case.get("expected", "redact_or_preserve"),
                            "category": case.get("category", name),
                            "fingerprint": hashlib.sha256(json.dumps(case, sort_keys=True, ensure_ascii=False).encode()).hexdigest()})
    metrics = {}
    for name in suites:
        rows = [row for row in results if row["suite"] == name and row["passed"] is not None]
        metrics[name] = {"total": len(rows), "passed": sum(row["passed"] for row in rows),
                         "accuracy": sum(row["passed"] for row in rows) / len(rows),
                         "not_evaluated": sum(row["suite"] == name and row["passed"] is None for row in results)}
    input_rows = [row for row in results if row["suite"] == "input_guardrail" and row["passed"] is not None]
    for expected, label in (("block", "attack_recall"), ("allow", "legitimate_acceptance")):
        rows = [row for row in input_rows if row["expected"] == expected]
        metrics[label] = sum(row["passed"] for row in rows) / len(rows) if rows else None
    return {"mode": "deterministic_offline", "scope": "guardrails_only",
            "metrics": metrics, "results": results}


def check_gate(report: dict, baseline: dict) -> dict:
    """Falha com casos removidos, regressão ou baseline que não pertence ao conjunto."""
    rows = report["results"]
    current_ids = {row["id"] for row in rows}
    expected_ids = set(baseline["case_ids"])
    known = baseline["known_failures"]
    failed = {row["id"] for row in rows if row["passed"] is False}
    regressions = sorted(failed - set(known))
    missing = sorted(expected_ids - current_ids)
    unreviewed = sorted(current_ids - expected_ids)
    invalid_known = sorted(set(known) - expected_ids)
    changed = sorted(row["id"] for row in rows if row["id"] in expected_ids
                     and row["fingerprint"] != baseline["fingerprints"].get(row["id"]))
    return {"passed": not (regressions or missing or unreviewed or invalid_known or changed),
            "regressions": regressions, "missing_cases": missing, "changed_cases": changed,
            "unreviewed_cases": unreviewed, "invalid_known_failures": invalid_known,
            "known_failures_still_present": sorted(failed & set(known)),
            "improved_cases": sorted(set(known) - failed)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "safety-evaluation.json")
    parser.add_argument("--baseline", type=Path, default=ROOT / "evals" / "safety-baseline.json")
    parser.add_argument("--strict", action="store_true", help="Reprova qualquer caso falho, inclusive lacunas conhecidas.")
    args = parser.parse_args(argv)
    try:
        report = evaluate(load_cases(DATASETS))
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        report["gate"] = check_gate(report, baseline)
        report["gate"]["policy"] = "strict" if args.strict else "no_regression"
        if args.strict and any(row["passed"] is False for row in report["results"]):
            report["gate"]["passed"] = False
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(f"Avaliação inválida: {error}")
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for name, metric in report["metrics"].items():
        print(f"{name}: {metric}")
    print(f"Gate: {'PASS' if report['gate']['passed'] else 'FAIL'}; relatório: {args.output}")
    return 0 if report["gate"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
