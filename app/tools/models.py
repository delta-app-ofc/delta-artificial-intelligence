from __future__ import annotations

from dataclasses import dataclass, field
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
    anomaly_detected: bool | None
    lpm_average: float | None = None
    device_id: str | None = None
    anomaly_reasons: tuple[str, ...] = ()
    anomaly_evidence: dict = field(default_factory=dict)
    detection_error: str | None = None
    detection_status: str | None = None


@dataclass(frozen=True)
class OrganizationProperty:
    """Uma unidade (tb_property) de uma organização vinculada ao usuário via tb_user_organization."""

    property_id: int
    name: str
    city: str
    state: str


@dataclass(frozen=True)
class Alert:
    """Um alerta de alerts_history (MongoDB)."""

    user_id: int
    device_id: str | None
    alert_type: str
    triggered_at: datetime
    resolved_at: datetime | None
    severity: str | None
    property_id: int | None = None
    title: str | None = None
    message: str | None = None
    source: str | None = None
    rule: str | None = None
    evidence: dict = field(default_factory=dict)
    dismissed_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        return self.resolved_at is None
