from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from bson import json_util

from app.tools.models import ConsumptionPoint
from detection.features import extract_features, hour_baseline_from_history
from detection.rules import calibrate_z_threshold
from detection.scorer import evaluate_window

MODELS_DIR = Path(__file__).resolve().parent / "models"


def _run_simulator_generator(
    simulator_path: Path, collection_name: str, amount: int, scenario: str | None = None
) -> list[dict]:
    args = ["python", "-m", "dataload.cli", collection_name, str(amount), "--dry-run"]
    if scenario:
        args += ["--scenario", scenario]
    result = subprocess.run(
        args, cwd=simulator_path, capture_output=True, text=True, check=True
    )
    return json_util.loads(result.stdout)


def load_normal_windows(simulator_path: Path, amount: int = 500) -> list[dict]:
    return _run_simulator_generator(simulator_path, "consumption_summary", amount, scenario="normal")


def load_leak_windows(simulator_path: Path, amount: int = 100) -> list[dict]:
    return _run_simulator_generator(simulator_path, "consumption_summary", amount, scenario="leak")


def _doc_to_point(doc: dict) -> ConsumptionPoint:
    return ConsumptionPoint(
        user_id=int(doc["user_id"]),
        window_started_at=doc["window_started_at"],
        window_finished_at=doc["window_finished_at"],
        consumption_liters=float(doc["consumption_liters"]),
        anomaly_detected=bool(doc.get("anomaly_detected", False)),
        lpm_average=doc.get("lpm_average"),
        device_id=doc.get("device_id"),
    )


def _count_flagged(docs: list[ConsumptionPoint], z_threshold: float) -> int:
    flagged = 0
    for i, doc in enumerate(docs):
        recent = docs[max(0, i - 24):i]
        hour_mean, hour_std = hour_baseline_from_history(doc.window_started_at.hour, docs)
        result = evaluate_window(doc, recent, hour_mean, hour_std, "RESIDENCIAL", z_threshold)
        if result.anomaly_detected:
            flagged += 1
    return flagged


def main(simulator_path: Path) -> None:
    normal_docs = [_doc_to_point(d) for d in load_normal_windows(simulator_path)]
    leak_docs = [_doc_to_point(d) for d in load_leak_windows(simulator_path)]

    normal_features = [
        extract_features(
            doc, normal_docs[max(0, i - 24):i],
            *hour_baseline_from_history(doc.window_started_at.hour, normal_docs),
        )
        for i, doc in enumerate(normal_docs)
    ]
    z_threshold = calibrate_z_threshold(
        [f.baseline_deviation for f in normal_features], percentile=99
    )

    detected = _count_flagged(leak_docs, z_threshold)
    false_positives = _count_flagged(normal_docs, z_threshold)

    print(f"Z_THRESHOLD calibrado: {z_threshold:.2f}")
    print(f"Vazamentos detectados: {detected}/{len(leak_docs)}")
    print(f"Falsos positivos (dados normais): {false_positives}/{len(normal_docs)}")

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    (MODELS_DIR / "z_threshold.json").write_text(json.dumps({"z_threshold": z_threshold}))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python -m detection.train <caminho-do-clone-do-simulador>", file=sys.stderr)
        raise SystemExit(1)
    main(Path(sys.argv[1]))
