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


def _copy_workspace(tmp_path):
    """Copia datasets e baseline para um diretório temporário, sem tocar nos arquivos reais."""
    datasets = tmp_path / "datasets"
    datasets.mkdir()
    for path in DATASETS.glob("*.json"):
        (datasets / path.name).write_bytes(path.read_bytes())
    baseline = tmp_path / "baseline.json"
    baseline.write_bytes((ROOT / "evals/safety-baseline.json").read_bytes())
    return datasets, baseline


def _mark_a_passing_case_as_known_failure(baseline_path):
    """Simula uma lacuna antiga que foi corrigida: o baseline ainda a lista como falha."""
    data = json.loads(baseline_path.read_text(encoding="utf-8"))
    passing = next(case_id for case_id in data["case_ids"] if case_id not in data["known_failures"])
    data["known_failures"][passing] = "lacuna antiga já corrigida"
    baseline_path.write_text(json.dumps(data), encoding="utf-8")
    return passing


def test_suite_without_evaluated_cases_does_not_divide_by_zero():
    suites = {
        "input_guardrail": [{"id": "x", "text": "abc", "expected": "block", "layer": "classifier"}],
        "output_pii": [{"id": "p", "response": "ok", "sensitive": [], "expected_response": "ok"}],
        "output_ownership": [{"id": "o", "user_id": 1, "response": "ok", "expected": "allow"}],
    }
    metrics = evaluate(suites)["metrics"]
    assert metrics["input_guardrail"]["accuracy"] is None
    assert metrics["input_guardrail"]["not_evaluated"] == 1
    assert metrics["attack_recall"] is None


def test_invalid_layer_is_rejected(tmp_path):
    datasets, _ = _copy_workspace(tmp_path)
    path = datasets / "input_guardrail.json"
    cases = json.loads(path.read_text(encoding="utf-8"))
    cases[0]["layer"] = "regras"
    path.write_text(json.dumps(cases), encoding="utf-8")
    with pytest.raises(ValueError, match="Camada inválida"):
        load_cases(datasets)


def test_cli_warns_when_a_known_gap_was_fixed(tmp_path, capsys):
    datasets, baseline = _copy_workspace(tmp_path)
    passing = _mark_a_passing_case_as_known_failure(baseline)
    code = main(["--datasets", str(datasets), "--baseline", str(baseline),
                 "--output", str(tmp_path / "report.json")])
    out = capsys.readouterr().out
    assert code == 0
    assert passing in out and "--update-baseline" in out


def test_update_baseline_locks_in_an_improvement(tmp_path):
    datasets, baseline = _copy_workspace(tmp_path)
    passing = _mark_a_passing_case_as_known_failure(baseline)
    arguments = ["--datasets", str(datasets), "--baseline", str(baseline)]
    assert main([*arguments, "--update-baseline"]) == 0
    assert passing not in json.loads(baseline.read_text(encoding="utf-8"))["known_failures"]
    assert main([*arguments, "--output", str(tmp_path / "report.json")]) == 0


def test_update_baseline_refuses_a_new_undocumented_failure(tmp_path):
    datasets, baseline = _copy_workspace(tmp_path)
    data = json.loads(baseline.read_text(encoding="utf-8"))
    del data["known_failures"][next(iter(data["known_failures"]))]
    baseline.write_text(json.dumps(data), encoding="utf-8")
    before = baseline.read_text(encoding="utf-8")
    assert main(["--datasets", str(datasets), "--baseline", str(baseline), "--update-baseline"]) == 1
    assert baseline.read_text(encoding="utf-8") == before


def test_expected_response_cannot_allow_declared_sensitive_value():
    report = evaluate({"output_pii": [{
        "id": "declared-secret", "response": "Identificador: TEST-PERSON-42.",
        "sensitive": ["TEST-PERSON-42"], "expected_response": "Identificador: TEST-PERSON-42.",
    }]})
    assert report["results"][0]["passed"] is False


@pytest.mark.parametrize("reason", [None, "", "   ", 42])
def test_update_rejects_missing_or_invalid_reason(tmp_path, reason):
    datasets, baseline = _copy_workspace(tmp_path)
    data = json.loads(baseline.read_text(encoding="utf-8"))
    data["known_failures"][next(iter(data["known_failures"]))] = reason
    baseline.write_text(json.dumps(data), encoding="utf-8")
    before = baseline.read_text(encoding="utf-8")
    assert main(["--datasets", str(datasets), "--baseline", str(baseline), "--update-baseline"]) == 2
    assert baseline.read_text(encoding="utf-8") == before


def test_update_cannot_remove_existing_case(tmp_path):
    datasets, baseline = _copy_workspace(tmp_path)
    path = datasets / "input_guardrail.json"
    cases = json.loads(path.read_text(encoding="utf-8"))
    cases.pop()
    path.write_text(json.dumps(cases), encoding="utf-8")
    before = baseline.read_text(encoding="utf-8")
    assert main(["--datasets", str(datasets), "--baseline", str(baseline), "--update-baseline"]) == 2
    assert baseline.read_text(encoding="utf-8") == before


def test_unmeasured_failure_is_not_an_improvement(evaluation):
    report, baseline = deepcopy(evaluation)
    row = next(row for row in report["results"] if row["passed"] is False)
    row["passed"] = None
    gate = check_gate(report, baseline)
    assert row["id"] not in gate["improved_cases"]
    assert row["id"] in gate["known_failures_not_evaluated"]


def test_update_keeps_a_failure_moved_to_the_llm_layer(tmp_path):
    datasets, baseline = _copy_workspace(tmp_path)
    data = json.loads(baseline.read_text(encoding="utf-8"))
    path = datasets / "input_guardrail.json"
    cases = json.loads(path.read_text(encoding="utf-8"))
    case = next(case for case in cases if case["id"] in data["known_failures"])
    case["layer"] = "classifier"
    path.write_text(json.dumps(cases), encoding="utf-8")
    assert main(["--datasets", str(datasets), "--baseline", str(baseline), "--update-baseline"]) == 0
    updated = json.loads(baseline.read_text(encoding="utf-8"))
    assert updated["known_failures"][case["id"]] == data["known_failures"][case["id"]]
