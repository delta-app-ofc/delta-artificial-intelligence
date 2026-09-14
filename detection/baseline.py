"""Baseline de consumo por usuário/hora, guardada no Mongo e atualizada de
forma incremental (EWMA) — em vez de reler 30 dias de histórico a cada janela.

Cada hora do dia recebe ~12 janelas de 5 min por dia. Pra ter um peso
equivalente à janela antiga de ~30 dias (~360 amostras), usamos
alpha = 2 / (360 + 1) — a mesma conta de sempre pra converter um período de
média móvel num fator de EMA.

Ordem importante para quem chama: ler a baseline, calcular o desvio da janela
atual contra ela, só DEPOIS atualizar com o valor atual. Atualizar antes de
comparar deixaria um vazamento grande "contaminar" a própria baseline que
serve pra detectá-lo.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.config import MONGO_DB_APP
from app.tools.db_mongo import get_client

EWMA_ALPHA = 2 / (360 + 1)

MIN_SAMPLES_FOR_DEVIATION = 3


def _collection():
    return get_client()[MONGO_DB_APP].user_hour_baseline


def ensure_indexes() -> None:
    _collection().create_index([("user_id", 1), ("hour", 1)], unique=True)


def read_baseline(user_id: int, hour: int) -> tuple[float, float, int]:
    """mean, variance, sample_count guardados, ou (0.0, 0.0, 0) se ainda não
    existir baseline pra esse usuário+hora."""
    doc = _collection().find_one({"user_id": user_id, "hour": hour})
    if doc is None:
        return 0.0, 0.0, 0
    return float(doc["mean"]), float(doc["variance"]), int(doc["sample_count"])


def ewma_update(mean: float, variance: float, count: int, value: float) -> tuple[float, float]:
    """A conta em si, separada do Mongo pra dar pra testar sem banco."""
    if count == 0:
        return value, 0.0
    diff = value - mean
    increment = EWMA_ALPHA * diff
    new_mean = mean + increment
    new_variance = (1 - EWMA_ALPHA) * (variance + diff * increment)
    return new_mean, new_variance


def update_baseline(user_id: int, hour: int, value: float) -> None:
    """Atualiza a baseline com um novo valor via EWMA, sem reler histórico."""
    mean, variance, count = read_baseline(user_id, hour)
    new_mean, new_variance = ewma_update(mean, variance, count, value)

    _collection().update_one(
        {"user_id": user_id, "hour": hour},
        {
            "$set": {
                "mean": new_mean,
                "variance": new_variance,
                "sample_count": count + 1,
                "updated_at": datetime.now(timezone.utc),
            }
        },
        upsert=True,
    )


def hour_std(variance: float, sample_count: int) -> float:
    """Desvio-padrão a partir da variância guardada, ou 0.0 enquanto a
    amostra for pequena demais pra ser confiável."""
    if sample_count < MIN_SAMPLES_FOR_DEVIATION:
        return 0.0
    return variance ** 0.5
