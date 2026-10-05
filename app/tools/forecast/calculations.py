"""Cálculo DETERMINÍSTICO da previsão de consumo — sem LLM. O LLM do Agente
de Previsão nunca calcula: só chama estas funções (via forecast/tools.py)."""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.tools.exceptions import ForecastUnavailableError
from app.tools.models import ConsumptionPoint, LastWaterBill

# Nº mínimo de dias distintos com leitura para o histórico ser considerado
# suficiente para projetar a partir do próprio consumo (senão usa a última conta).
MIN_HISTORY_DAYS = 7

# Janela usada para a média móvel diária.
MOVING_AVERAGE_WINDOW_DAYS = 14

# Nº mínimo de dias distintos para classificar tendência.
MIN_TREND_DAYS = 6

# Abaixo desta variação percentual, a tendência é considerada estável.
STABLE_TREND_THRESHOLD_PCT = 5.0

_LITERS_PER_M3 = Decimal("1000")


@dataclass(frozen=True)
class ConsumptionProjection:
    month_consumption_so_far_liters: float
    daily_average_liters: float
    remaining_days: int
    days_in_month: int
    month_projection_liters: float


@dataclass(frozen=True)
class Trend:
    direction: str  # "up" | "down" | "stable" | "undefined"
    recent_average_liters_per_day: float
    previous_average_liters_per_day: float
    variation_pct: float | None


@dataclass(frozen=True)
class BillEstimate:
    estimated_value: Decimal
    estimated_m3: Decimal
    base: str  # "last_bill" | "history_projection"
    rate_m3: Decimal | None


@dataclass(frozen=True)
class TargetRisk:
    assessable: bool
    at_risk: bool
    monthly_target_liters: float | None
    month_projection_liters: float | None
    difference_pct: float | None


@dataclass(frozen=True)
class FullForecast:
    projection: ConsumptionProjection
    trend: Trend
    bill: BillEstimate | None
    target_risk: TargetRisk
    has_enough_history: bool
    notes: list[str] = field(default_factory=list)


def _daily_series(history: list[ConsumptionPoint]) -> dict[date, float]:
    series: dict[date, float] = {}
    for point in history:
        day = point.window_started_at.date()
        series[day] = series.get(day, 0.0) + float(point.consumption_liters)
    return series


def _days_in_month(today: date) -> int:
    return calendar.monthrange(today.year, today.month)[1]


def has_enough_history(history: list[ConsumptionPoint]) -> bool:
    return len(_daily_series(history)) >= MIN_HISTORY_DAYS


def project_month_consumption(history: list[ConsumptionPoint], today: date) -> ConsumptionProjection:
    series = _daily_series(history)
    days_in_month = _days_in_month(today)
    remaining_days = days_in_month - today.day

    month_start = today.replace(day=1)
    month_consumption = sum(
        liters for day, liters in series.items() if month_start <= day <= today
    )

    window_limit = today - timedelta(days=MOVING_AVERAGE_WINDOW_DAYS)
    window = {
        day: liters
        for day, liters in series.items()
        if window_limit < day <= today
    }
    if window:
        span = (max(window) - min(window)).days + 1
        daily_average = sum(window.values()) / span
    else:
        daily_average = 0.0

    projection = month_consumption + daily_average * remaining_days
    return ConsumptionProjection(
        month_consumption_so_far_liters=round(month_consumption, 2),
        daily_average_liters=round(daily_average, 2),
        remaining_days=remaining_days,
        days_in_month=days_in_month,
        month_projection_liters=round(projection, 2),
    )


def estimate_next_bill(
    history: list[ConsumptionPoint],
    last_bill: LastWaterBill | None,
    region_rate: Decimal | None,
    today: date,
) -> BillEstimate | None:
    enough_history = has_enough_history(history)

    if not enough_history or region_rate is None:
        if last_bill is None:
            return None
        return BillEstimate(
            estimated_value=Decimal(last_bill.total_value).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            ),
            estimated_m3=Decimal(last_bill.m3_value),
            base="last_bill",
            rate_m3=None,
        )

    projection = project_month_consumption(history, today)
    m3 = (Decimal(str(projection.month_projection_liters)) / _LITERS_PER_M3).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    value = (m3 * region_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return BillEstimate(
        estimated_value=value,
        estimated_m3=m3,
        base="history_projection",
        rate_m3=Decimal(region_rate),
    )


def calculate_trend(history: list[ConsumptionPoint], today: date) -> Trend:
    series = _daily_series(history)
    days = sorted(d for d in series if d <= today)

    if len(days) < MIN_TREND_DAYS:
        return Trend("undefined", 0.0, 0.0, None)

    middle = len(days) // 2
    previous_days, recent_days = days[:middle], days[middle:]
    previous_average = sum(series[d] for d in previous_days) / len(previous_days)
    recent_average = sum(series[d] for d in recent_days) / len(recent_days)

    if previous_average == 0:
        variation = None
        direction = "up" if recent_average > 0 else "stable"
    else:
        variation = (recent_average - previous_average) / previous_average * 100
        if abs(variation) < STABLE_TREND_THRESHOLD_PCT:
            direction = "stable"
        elif variation > 0:
            direction = "up"
        else:
            direction = "down"

    return Trend(
        direction=direction,
        recent_average_liters_per_day=round(recent_average, 2),
        previous_average_liters_per_day=round(previous_average, 2),
        variation_pct=round(variation, 2) if variation is not None else None,
    )


def assess_target_risk(
    month_projection_liters: float, daily_target: float | None, days_in_month: int
) -> TargetRisk:
    if daily_target is None:
        return TargetRisk(False, False, None, month_projection_liters, None)

    monthly_target = daily_target * days_in_month
    difference_pct = (
        (month_projection_liters - monthly_target) / monthly_target * 100 if monthly_target else None
    )
    return TargetRisk(
        assessable=True,
        at_risk=month_projection_liters > monthly_target,
        monthly_target_liters=round(monthly_target, 2),
        month_projection_liters=round(month_projection_liters, 2),
        difference_pct=round(difference_pct, 2) if difference_pct is not None else None,
    )


def calculate_full_forecast(
    *,
    can_estimate: bool,
    history: list[ConsumptionPoint],
    last_bill: LastWaterBill | None,
    region_rate: Decimal | None,
    daily_target: float | None,
    today: date,
) -> FullForecast:
    if not can_estimate:
        raise ForecastUnavailableError(
            "fn_user_can_estimate retornou False: usuário sem cadastro suficiente "
            "para estimativas. Nenhum cálculo foi executado."
        )

    notes: list[str] = []
    enough_history = has_enough_history(history)
    if not enough_history:
        notes.append(
            "Histórico de consumo insuficiente (< "
            f"{MIN_HISTORY_DAYS} dias); estimativas partem da última conta quando disponível."
        )
    if region_rate is None:
        notes.append("Sem tarifa vigente disponível para a região.")
    if daily_target is None:
        notes.append("Meta diária não cadastrada; risco de meta não avaliado.")

    projection = project_month_consumption(history, today)
    trend = calculate_trend(history, today)
    bill = estimate_next_bill(history, last_bill, region_rate, today)
    if bill is None:
        notes.append(
            "Sem base para estimar a próxima conta (sem histórico suficiente e sem conta anterior)."
        )
    target_risk = assess_target_risk(
        projection.month_projection_liters, daily_target, projection.days_in_month
    )

    return FullForecast(
        projection=projection,
        trend=trend,
        bill=bill,
        target_risk=target_risk,
        has_enough_history=enough_history,
        notes=notes,
    )
