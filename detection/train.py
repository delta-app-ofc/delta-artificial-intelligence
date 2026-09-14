"""CLI: monta o dataset (normal + vazamento, os dois vindos do --dry-run do
simulador), calibra o Z_THRESHOLD, treina o Isolation Forest, salva tudo e
imprime as métricas de validação.

Uso:
    python -m detection.train <caminho-do-clone-do-delta-hardware-data-simulator>
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from bson import json_util
from sklearn.model_selection import train_test_split

from detection.features import extract_features, hour_baseline_from_history
from detection.model import save_model, train_model
from detection.rules import calibrate_z_threshold


def _run_simulator_generator(
    simulator_path: Path, collection_name: str, amount: int, scenario: str | None = None
) -> list[dict]:
    """Roda um gerador do delta-hardware-data-simulator em modo --dry-run
    (só imprime os documentos, não insere em lugar nenhum) e devolve o
    resultado já parseado. Mantém os dois repositórios totalmente
    desacoplados: sem estado compartilhado no Mongo, sem ambiguidade sobre
    qual user_id pertence a qual cenário."""
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


def _doc_to_point(doc: dict):
    from app.tools.models import ConsumptionPoint

    return ConsumptionPoint(
        user_id=int(doc["user_id"]),
        window_started_at=doc["window_started_at"],
        window_finished_at=doc["window_finished_at"],
        consumption_liters=float(doc["consumption_liters"]),
        anomaly_detected=bool(doc.get("anomaly_detected", False)),
        lpm_average=doc.get("lpm_average"),
        device_id=doc.get("device_id"),
    )


def main(simulator_path: Path) -> None:
    normal_docs = [_doc_to_point(d) for d in load_normal_windows(simulator_path)]
    leak_docs = [_doc_to_point(d) for d in load_leak_windows(simulator_path)]

    # Treino em lote: calcula a baseline direto do próprio lote sintético
    # (hour_baseline_from_history), diferente do caminho ao vivo, que usa a
    # baseline incremental guardada (detection/baseline.py).
    normal_features = [
        extract_features(
            doc, normal_docs[max(0, i - 24):i],
            *hour_baseline_from_history(doc.window_started_at.hour, normal_docs),
        )
        for i, doc in enumerate(normal_docs)
    ]
    leak_features = [
        extract_features(
            doc, leak_docs[max(0, i - 24):i],
            *hour_baseline_from_history(doc.window_started_at.hour, leak_docs),
        )
        for i, doc in enumerate(leak_docs)
    ]

    z_threshold = calibrate_z_threshold(
        [f.baseline_deviation for f in normal_features], percentile=99
    )

    # train_test_split é do scikit-learn: separa aleatoriamente uma parte
    # (aqui, 20%) pra validação, deixando o resto pro treino.
    train_set, validation_set = train_test_split(normal_features, test_size=0.2, random_state=42)
    model = train_model([f.to_vector() for f in train_set])

    detected = sum(model.predict([f.to_vector()])[0] == -1 for f in leak_features)
    false_positives = sum(model.predict([f.to_vector()])[0] == -1 for f in validation_set)

    print(f"Z_THRESHOLD calibrado: {z_threshold:.2f}")
    print(f"Vazamentos detectados: {detected}/{len(leak_features)}")
    print(f"Falsos positivos (dados normais): {false_positives}/{len(validation_set)}")

    save_model(model)
    (Path(__file__).resolve().parent / "models" / "z_threshold.json").write_text(
        json.dumps({"z_threshold": z_threshold})
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python -m detection.train <caminho-do-clone-do-simulador>", file=sys.stderr)
        raise SystemExit(1)
    main(Path(sys.argv[1]))
