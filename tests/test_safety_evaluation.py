"""Verifica que o gate detecta regressões e alterações no conjunto avaliado."""
import json
from copy import deepcopy

import pytest

from scripts.evaluate_safety import DATASETS, ROOT, check_gate, evaluate, load_cases, main


@pytest.fixture(scope="module")
def evaluation():
    report = evaluate(load_cases(DATASETS))
    baseline = json.loads((ROOT / "evals/safety-baseline.json").read_text(encoding="utf-8"))
    return report, baseline


def test_current_baseline_reports_known_gaps(evaluation):
    report, baseline = evaluation
    gate = check_gate(report, baseline)
    assert gate["passed"]
    assert gate["known_failures_still_present"]
    assert report["scope"] == "guardrails_only"
    assert report["metrics"]["attack_recall"] < 1


def test_new_failure_blocks_gate(evaluation):
    report, baseline = deepcopy(evaluation)
    row = next(row for row in report["results"] if row["passed"])
    row["passed"] = False
    gate = check_gate(report, baseline)
    assert not gate["passed"]
    assert row["id"] in gate["regressions"]


def test_removed_case_blocks_gate(evaluation):
    report, baseline = deepcopy(evaluation)
    removed = report["results"].pop()
    gate = check_gate(report, baseline)
    assert not gate["passed"]
    assert gate["missing_cases"] == [removed["id"]]


def test_changed_case_blocks_gate(evaluation):
    report, baseline = deepcopy(evaluation)
    report["results"][0]["fingerprint"] = "changed"
    assert not check_gate(report, baseline)["passed"]


def test_improvement_passes_without_hiding_it(evaluation):
    report, baseline = deepcopy(evaluation)
    row = next(row for row in report["results"] if not row["passed"])
    row["passed"] = True
    gate = check_gate(report, baseline)
    assert gate["passed"]
    assert row["id"] in gate["improved_cases"]


def test_duplicate_dataset_ids_rejected(tmp_path):
    for path in DATASETS.glob("*.json"):
        (tmp_path / path.name).write_bytes(path.read_bytes())
    path = tmp_path / "input_guardrail.json"
    cases = json.loads(path.read_text(encoding="utf-8"))
    cases.append(cases[0])
    path.write_text(json.dumps(cases), encoding="utf-8")
    with pytest.raises(ValueError, match="repetido"):
        load_cases(tmp_path)


def test_cli_saves_report_and_returns_success(tmp_path):
    output = tmp_path / "report.json"
    assert main(["--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["gate"]["passed"]


def test_cli_missing_baseline_is_error(tmp_path):
    assert main(["--baseline", str(tmp_path / "missing.json")]) == 2


def test_strict_mode_rejects_existing_gaps(tmp_path):
    output = tmp_path / "strict.json"
    assert main(["--strict", "--output", str(output)]) == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["gate"]["policy"] == "strict"
    assert not report["gate"]["passed"]


def test_llm_cases_are_reported_as_not_evaluated(evaluation):
    report, _ = evaluation
    pending = [row for row in report["results"] if row["passed"] is None]
    assert {row["id"] for row in pending} == {"atk-039", "atk-040", "atk-041", "atk-042"}
    assert report["metrics"]["input_guardrail"]["not_evaluated"] == 4
    assert all(row["actual"] == "not_evaluated_requires_llm" for row in pending)
