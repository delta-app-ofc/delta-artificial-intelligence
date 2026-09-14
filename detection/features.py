"""Extração das features usadas pelas regras e pelo modelo de detecção."""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.tools.models import ConsumptionPoint

OVERNIGHT_START_HOUR = 0
OVERNIGHT_END_HOUR = 6
MIN_FLOW_LITERS = 0.2  # abaixo disso é ruído do sensor, não "fluxo"


@dataclass(frozen=True)
class WindowFeatures:
    consumption_liters: float
    lpm_average: float
    hour_sin: float
    hour_cos: float
    is_overnight: int
    consecutive_flow_windows: int
    baseline_deviation: float

    def to_vector(self) -> list[float]:
        """Ordem fixa usada pelo IsolationForest."""
        return [
            self.consumption_liters, self.lpm_average, self.hour_sin,
            self.hour_cos, float(self.is_overnight),
            float(self.consecutive_flow_windows), self.baseline_deviation,
        ]


def _cyclical_hour(hour: int) -> tuple[float, float]:
    """Codifica a hora do dia em seno/cosseno, pra hora 23 ficar "perto"
    da hora 0 (evita que o modelo veja meia-noite e 23h como opostos)."""
    angle = 2 * math.pi * hour / 24
    return math.sin(angle), math.cos(angle)


def _count_consecutive_flow(current: ConsumptionPoint, recent_sorted: list[ConsumptionPoint]) -> int:
    """Quantas janelas seguidas (incluindo a atual), olhando pra trás no
    histórico do MESMO device, tiveram fluxo acima do limiar mínimo.

    "Seguidas" aqui é literal: exige que cada janela termine exatamente onde a
    próxima começa (sem buraco). Isso importa porque três rajadas isoladas do
    mesmo dia (ex.: banho de manhã, almoço, banho à noite) não podem contar
    como "fluxo contínuo" só por estarem as três no histórico recente — só
    contam janelas realmente ininterruptas no tempo.
    """
    if current.consumption_liters <= MIN_FLOW_LITERS:
        return 0
    count = 1
    expected_end = current.window_started_at
    for window in reversed(recent_sorted):  # mais recente -> mais antiga
        if window.consumption_liters <= MIN_FLOW_LITERS:
            break
        if window.window_finished_at != expected_end:
            break  # tem um buraco no tempo: a sequência contínua para aqui
        count += 1
        expected_end = window.window_started_at
    return count


def hour_baseline_from_history(hour: int, long_history: list[ConsumptionPoint]) -> tuple[float, float]:
    """Média e desvio-padrão do consumo do usuário, só nas janelas da MESMA
    hora do dia (comparar 3h com outras 3h, não com o dia todo).

    Usada só em treino/calibração em lote (detection/train.py), sobre dados
    sintéticos. No caminho ao vivo (detection/watcher.py), a baseline vem
    guardada e atualizada incrementalmente em detection/baseline.py — não
    recalculada do histórico a cada janela.
    """
    values = [j.consumption_liters for j in long_history if j.window_started_at.hour == hour]
    if len(values) < 3:  # histórico curto demais pra uma baseline confiável
        return 0.0, 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return mean, variance ** 0.5


def extract_features(
    window: ConsumptionPoint,
    recent_history: list[ConsumptionPoint],  # últimas ~2h do mesmo device, ordenado
    hour_mean: float,
    hour_std: float,
) -> WindowFeatures:
    hour = window.window_started_at.hour
    hour_sin, hour_cos = _cyclical_hour(hour)
    baseline_deviation = (
        (window.consumption_liters - hour_mean) / hour_std if hour_std > 0 else 0.0
    )

    return WindowFeatures(
        consumption_liters=window.consumption_liters,
        lpm_average=window.lpm_average or 0.0,
        hour_sin=hour_sin, hour_cos=hour_cos,
        is_overnight=int(OVERNIGHT_START_HOUR <= hour < OVERNIGHT_END_HOUR),
        consecutive_flow_windows=_count_consecutive_flow(window, recent_history),
        baseline_deviation=baseline_deviation,
    )
