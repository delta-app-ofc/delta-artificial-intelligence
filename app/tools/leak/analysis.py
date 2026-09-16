"""Resumo DESCRITIVO de janelas de consumo já sinalizadas como anômalas.

Função pura: só AGREGA o que db_mongo.get_anomalous_consumption_windows já
retornou (janelas com anomaly_detected true, sinalizadas por outro componente
do sistema — o motor de detecção no repositório delta-business-rules). Não
cria limiar novo, não decide por conta própria se algo é ou não indício —
isso violaria a regra do prompt do Agente de Vazamento ("nunca invente
limiares/padrões").

O objetivo é só dar ao agente material para explicar, em linguagem natural, o
padrão que já foi sinalizado (quantas janelas, quando começaram, quanto tempo
duraram, quantas foram de madrugada).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.tools.models import ConsumptionPoint

# Faixa de "madrugada" usada só para DESCREVER as janelas (00:00-05:59). Não é
# um critério de detecção: as janelas já chegam aqui marcadas como anômalas.
_OVERNIGHT_START_HOUR = 0
_OVERNIGHT_END_HOUR = 6


@dataclass(frozen=True)
class AnomalySummary:
    total_windows: int
    first_occurrence: datetime | None
    last_occurrence: datetime | None
    total_duration_minutes: float
    total_liters: float
    overnight_windows: int


def _sort_by_start(windows: list[ConsumptionPoint]) -> list[ConsumptionPoint]:
    """Ordena as janelas da mais antiga para a mais recente."""
    return sorted(windows, key=_window_start)


def _window_start(window: ConsumptionPoint) -> datetime:
    return window.window_started_at


def _is_overnight(window: ConsumptionPoint) -> bool:
    hour = window.window_started_at.hour
    return _OVERNIGHT_START_HOUR <= hour < _OVERNIGHT_END_HOUR


def summarize_anomalous_windows(windows: list[ConsumptionPoint]) -> AnomalySummary:
    """Agrega uma lista de janelas anômalas num resumo descritivo, com um
    laço só (mais fácil de acompanhar do que várias contas separadas)."""
    if not windows:
        return AnomalySummary(
            total_windows=0, first_occurrence=None, last_occurrence=None,
            total_duration_minutes=0.0, total_liters=0.0, overnight_windows=0,
        )

    sorted_windows = _sort_by_start(windows)

    total_duration_minutes = 0.0
    total_liters = 0.0
    overnight_windows = 0

    for window in sorted_windows:
        duration = window.window_finished_at - window.window_started_at
        total_duration_minutes += duration.total_seconds() / 60
        total_liters += float(window.consumption_liters)
        if _is_overnight(window):
            overnight_windows += 1

    return AnomalySummary(
        total_windows=len(sorted_windows),
        first_occurrence=sorted_windows[0].window_started_at,
        last_occurrence=sorted_windows[-1].window_started_at,
        total_duration_minutes=round(total_duration_minutes, 2),
        total_liters=round(total_liters, 2),
        overnight_windows=overnight_windows,
    )
