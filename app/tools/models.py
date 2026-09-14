"""Estruturas de dados retornadas pelas tools de acesso a dados.

São dataclasses para deixar explícito o formato dos
dados que trafegam entre as tools, os cálculos e os agentes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True)
class LastWaterBill:
    """Uma linha de tb_last_water_bill (PostgreSQL)."""

    user_id: int
    month: date
    total_value: Decimal
    m3_value: Decimal


@dataclass(frozen=True)
class ConsumptionPoint:
    """Uma janela de consumption_summary (MongoDB)."""

    user_id: int
    window_started_at: datetime
    window_finished_at: datetime
    consumption_liters: float
    anomaly_detected: bool
    lpm_average: float | None = None
    device_id: str | None = None


@dataclass(frozen=True)
class Alert:
    """Um alerta de alerts_history (MongoDB)."""

    user_id: int
    device_id: str
    alert_type: str
    triggered_at: datetime
    resolved_at: datetime | None
    severity: str | None

    @property
    def is_active(self) -> bool:
        return self.resolved_at is None
