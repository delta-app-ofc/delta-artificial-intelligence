"""Loop de Change Stream: avalia cada janela nova assim que ela é inserida.

Exige o Mongo rodando como replica set (mesmo que de 1 nó só) — ver
docker-compose.dev.yml e detection/README.md.
"""

from __future__ import annotations

from datetime import timedelta

from app.config import MONGO_DB_APP, MONGO_DB_TELEMETRY
from app.tools.db_mongo import get_client
from app.tools.db_postgres import get_property_classification
from app.tools.models import ConsumptionPoint
from detection import baseline, model as model_module
from detection.scorer import DetectionResult, evaluate_window


def _doc_to_consumption_point(doc: dict) -> ConsumptionPoint:
    """Converte um documento cru do Mongo no dataclass que o resto do código usa."""
    return ConsumptionPoint(
        user_id=int(doc["user_id"]),
        window_started_at=doc["window_started_at"],
        window_finished_at=doc["window_finished_at"],
        consumption_liters=float(doc["consumption_liters"]),
        anomaly_detected=bool(doc.get("anomaly_detected", False)),
        lpm_average=doc.get("lpm_average"),
        device_id=doc.get("device_id"),
    )


def _fetch_history(collection, doc: dict, *, hours: int) -> list[ConsumptionPoint]:
    """Busca janelas anteriores do MESMO device, terminando bem antes do
    início da janela atual (`doc`)."""
    since = doc["window_started_at"] - timedelta(hours=hours)
    cursor = collection.find({
        "device_id": doc["device_id"],
        "window_started_at": {"$gte": since, "$lt": doc["window_started_at"]},
    }).sort("window_started_at", 1)
    return [_doc_to_consumption_point(d) for d in cursor]


def process_event(
    doc, recent_history, hour_mean, hour_std, property_classification, model, z_threshold
) -> DetectionResult:
    """Lógica pura (testável sem Mongo real) — o `watch()` só chama isto."""
    window = _doc_to_consumption_point(doc)
    return evaluate_window(window, recent_history, hour_mean, hour_std, property_classification, model, z_threshold)


def run(z_threshold: float) -> None:
    model = model_module.load_model()
    telemetry = get_client()[MONGO_DB_TELEMETRY]
    collection = telemetry.consumption_summary

    with collection.watch(
        [{"$match": {"operationType": "insert"}}], full_document="updateLookup"
    ) as stream:
        for event in stream:                        # fica parado até chegar algo novo
            doc = event["fullDocument"]
            hour = doc["window_started_at"].hour
            recent_history = _fetch_history(collection, doc, hours=2)
            classification = get_property_classification(doc["user_id"])

            # Lê a baseline ANTES de atualizar, senão a própria janela atual
            # contaminaria a média/desvio que serve pra avaliá-la.
            mean, variance, count = baseline.read_baseline(doc["user_id"], hour)
            hour_std = baseline.hour_std(variance, count)

            result = process_event(doc, recent_history, mean, hour_std, classification, model, z_threshold)
            baseline.update_baseline(doc["user_id"], hour, float(doc["consumption_liters"]))

            collection.update_one({"_id": doc["_id"]}, {"$set": {"anomaly_detected": result.anomaly_detected}})
            if result.anomaly_detected and "continuous_flow" in result.reasons:
                get_client()[MONGO_DB_APP].alerts_history.insert_one({
                    "device_id": doc["device_id"], "user_id": doc["user_id"],
                    "alert_type": "vazamento_continuo",  # mantido como está: é um valor do enum
                    "triggered_at": doc["window_started_at"],  # alert_type já existente, em
                    "resolved_at": None, "severity": "medium",  # português, compartilhado com o delta-nosql-database
                })


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    config_path = Path(__file__).resolve().parent / "models" / "z_threshold.json"
    threshold = json.loads(config_path.read_text())["z_threshold"] if config_path.exists() else 3.0
    if len(sys.argv) > 1:
        threshold = float(sys.argv[1])
    run(threshold)
