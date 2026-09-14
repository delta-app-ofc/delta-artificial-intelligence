"""Treino/carregamento do Isolation Forest (scikit-learn) — detecção não-supervisionada."""

from __future__ import annotations

from pathlib import Path

import joblib
from sklearn.ensemble import IsolationForest

MODEL_PATH = Path(__file__).resolve().parent / "models" / "isolation_forest.joblib"


def train_model(feature_matrix: list[list[float]], contamination: float = 0.02) -> IsolationForest:
    """`contamination` = fração esperada de outliers nos dados de treino
    (majoritariamente normais). Calibrado olhando a taxa de falso positivo
    nos dados normais de validação — ver train.py."""
    model = IsolationForest(n_estimators=200, contamination=contamination, random_state=42)
    model.fit(feature_matrix)
    return model


def save_model(model: IsolationForest) -> None:
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH)


def load_model() -> IsolationForest:
    if not MODEL_PATH.exists():
        raise FileNotFoundError("Modelo não encontrado. Rode `python -m detection.train` primeiro.")
    return joblib.load(MODEL_PATH)
