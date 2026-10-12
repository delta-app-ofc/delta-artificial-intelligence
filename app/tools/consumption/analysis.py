"""Períodos e cálculos descritivos do consumo registrado, sem acesso a bancos."""

from __future__ import annotations

import calendar
import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.tools.models import ConsumptionPoint

DEFAULT_TIMEZONE = "America/Sao_Paulo"
MAX_PERIOD_DAYS = 366

PeriodName = Literal[
    "today",
    "yesterday",
    "this_week",
    "this_month",
    "last_7_days",
    "last_30_days",
    "previous_7_days",
    "previous_30_days",
    "previous_month_same_days",
    "custom",
]


class InvalidConsumptionInput(ValueError):
    """A solicitação não descreve um período válido de consumo realizado."""


class InconsistentConsumptionData(ValueError):
    """A fonte contém medições que não podem ser agregadas com segurança."""


@dataclass(frozen=True)
class ConsumptionPeriod:
    """Intervalo local semiaberto usado nas consultas de consumo."""

    start: datetime
    end: datetime
    timezone_name: str
    label: str
    notes: tuple[str, ...] = ()

    @property
    def last_included_date(self) -> date:
        """Última data tocada pelo intervalo, respeitando o fim exclusivo."""
        if self.end.timetz().replace(tzinfo=None) == time.min:
            return self.end.date() - timedelta(days=1)
        return self.end.date()

    @property
    def calendar_days(self) -> int:
        if self.end <= self.start:
            return 0
        return (self.last_included_date - self.start.date()).days + 1

    def as_dict(self) -> dict[str, str | int]:
        return {
            "label": self.label,
            "start_inclusive": self.start.isoformat(),
            "end_exclusive": self.end.isoformat(),
            "timezone": self.timezone_name,
            "calendar_days_touched": self.calendar_days,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class DailyConsumption:
    """Consumo agregado de uma data local, preservando zero como medição."""

    day: date
    liters: float


@dataclass(frozen=True)
class ConsumptionAggregate:
    """Métricas determinísticas resumidas por dia com registro."""

    daily_totals: tuple[DailyConsumption, ...]
    total_liters: float | None
    days_with_records: int
    average_liters_per_recorded_day: float | None
    first_recorded_date: date | None
    last_recorded_date: date | None
    last_reading_at: datetime | None
    last_available_date: date | None
    missing_days_between_records: int
    windows_crossing_local_midnight: int = 0
    windows_crossing_period_end: int = 0

    @property
    def has_data(self) -> bool:
        return self.days_with_records > 0

    @property
    def has_gaps_between_recorded_days(self) -> bool:
        return self.missing_days_between_records > 0

    def summary_dict(self) -> dict[str, object]:
        return {
            "total_liters": self.total_liters,
            "days_with_records": self.days_with_records,
            "average_liters_per_recorded_day": self.average_liters_per_recorded_day,
            "average_denominator": "dias com registros",
            "first_recorded_date": (
                self.first_recorded_date.isoformat() if self.first_recorded_date else None
            ),
            "last_recorded_date": (
                self.last_recorded_date.isoformat() if self.last_recorded_date else None
            ),
            "last_reading_at": (
                self.last_reading_at.isoformat() if self.last_reading_at else None
            ),
            "last_available_date": (
                self.last_available_date.isoformat() if self.last_available_date else None
            ),
            "missing_days_between_recorded_dates": self.missing_days_between_records,
            "has_gaps_between_recorded_dates": self.has_gaps_between_recorded_days,
            "windows_crossing_local_midnight": self.windows_crossing_local_midnight,
            "windows_crossing_period_end": self.windows_crossing_period_end,
        }


def _zone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, TypeError, ValueError) as exc:
        raise InvalidConsumptionInput("O fuso horário configurado não é válido.") from exc


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise InvalidConsumptionInput(f"{field_name} precisa ter fuso horário explícito.")
    return value.astimezone(timezone.utc)


def _record_aware_utc(value: datetime, field_name: str) -> datetime:
    try:
        return _aware_utc(value, field_name)
    except InvalidConsumptionInput as exc:
        raise InconsistentConsumptionData(
            "A fonte contém data ou horário sem fuso horário explícito."
        ) from exc


def _local_midnight(day: date, zone: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=zone)


def _date_value(value: str | date | None, field_name: str) -> date:
    if isinstance(value, datetime):
        raise InvalidConsumptionInput(f"{field_name} deve usar o formato AAAA-MM-DD.")
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise InvalidConsumptionInput(f"Informe {field_name} no formato AAAA-MM-DD.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise InvalidConsumptionInput(
            f"{field_name} deve usar uma data válida no formato AAAA-MM-DD."
        ) from exc
    if parsed.isoformat() != value:
        raise InvalidConsumptionInput(f"{field_name} deve usar o formato AAAA-MM-DD.")
    return parsed


def _previous_month_start(day: date) -> date:
    if day.month == 1:
        return date(day.year - 1, 12, 1)
    return date(day.year, day.month - 1, 1)


def _rolling_period(
    *, now_utc: datetime, days: int, timezone_name: str, label: str
) -> ConsumptionPeriod:
    zone = _zone(timezone_name)
    end = now_utc.astimezone(zone)
    start = (now_utc - timedelta(days=days)).astimezone(zone)
    return ConsumptionPeriod(start, end, timezone_name, label)


def resolve_period(
    period: str,
    *,
    now: datetime,
    timezone_name: str = DEFAULT_TIMEZONE,
    start_date: str | date | None = None,
    end_date: str | date | None = None,
) -> ConsumptionPeriod:
    """Resolve um período nomeado ou datas locais inclusivas em [início, fim)."""
    now_utc = _aware_utc(now, "now")
    zone = _zone(timezone_name)
    local_now = now_utc.astimezone(zone)

    if period == "custom":
        if start_date is None or end_date is None:
            raise InvalidConsumptionInput(
                "Para um período personalizado, informe início e fim no formato AAAA-MM-DD."
            )
        first_day = _date_value(start_date, "início")
        last_day = _date_value(end_date, "fim")
        if first_day > last_day:
            raise InvalidConsumptionInput("A data inicial é posterior à data final.")
        if last_day > local_now.date():
            raise InvalidConsumptionInput("O período não pode incluir datas futuras.")
        if (last_day - first_day).days + 1 > MAX_PERIOD_DAYS:
            raise InvalidConsumptionInput("O período máximo permitido é de 366 dias.")

        start = _local_midnight(first_day, zone)
        end = _local_midnight(last_day + timedelta(days=1), zone)
        notes: tuple[str, ...] = ()
        if last_day == local_now.date():
            end = local_now
            notes = ("A data final de hoje foi limitada ao instante da consulta.",)
        return ConsumptionPeriod(
            start,
            end,
            timezone_name,
            f"datas inclusivas {first_day.isoformat()} a {last_day.isoformat()}",
            notes,
        )

    if start_date is not None or end_date is not None:
        raise InvalidConsumptionInput(
            "Use period='custom' ao informar datas de início e fim."
        )

    local_day = local_now.date()
    if period == "today":
        start = _local_midnight(local_day, zone)
        return ConsumptionPeriod(
            start,
            local_now,
            timezone_name,
            "hoje",
            ("O período de hoje termina no instante da consulta.",),
        )
    if period == "yesterday":
        start = _local_midnight(local_day - timedelta(days=1), zone)
        end = _local_midnight(local_day, zone)
        return ConsumptionPeriod(start, end, timezone_name, "ontem")
    if period == "this_week":
        monday = local_day - timedelta(days=local_day.weekday())
        start = _local_midnight(monday, zone)
        return ConsumptionPeriod(
            start,
            local_now,
            timezone_name,
            "esta semana até agora",
            ("O dia atual é parcial até o instante da consulta.",),
        )
    if period == "this_month":
        start = _local_midnight(local_day.replace(day=1), zone)
        return ConsumptionPeriod(
            start,
            local_now,
            timezone_name,
            "este mês até agora",
            ("O dia atual é parcial até o instante da consulta.",),
        )
    if period == "last_7_days":
        return _rolling_period(
            now_utc=now_utc, days=7, timezone_name=timezone_name, label="últimos 7 dias móveis"
        )
    if period == "last_30_days":
        return _rolling_period(
            now_utc=now_utc, days=30, timezone_name=timezone_name, label="últimos 30 dias móveis"
        )
    if period == "previous_7_days":
        end_utc = now_utc - timedelta(days=7)
        start_utc = end_utc - timedelta(days=7)
        return ConsumptionPeriod(
            start_utc.astimezone(zone),
            end_utc.astimezone(zone),
            timezone_name,
            "7 dias móveis anteriores",
        )
    if period == "previous_30_days":
        end_utc = now_utc - timedelta(days=30)
        start_utc = end_utc - timedelta(days=30)
        return ConsumptionPeriod(
            start_utc.astimezone(zone),
            end_utc.astimezone(zone),
            timezone_name,
            "30 dias móveis anteriores",
        )
    if period == "previous_month_same_days":
        previous_start_day = _previous_month_start(local_day)
        previous_days = min(local_day.day, calendar.monthrange(
            previous_start_day.year, previous_start_day.month
        )[1])
        previous_end_day = previous_start_day + timedelta(days=previous_days)
        return ConsumptionPeriod(
            _local_midnight(previous_start_day, zone),
            _local_midnight(previous_end_day, zone),
            timezone_name,
            "mês passado até o mesmo número de dias do mês atual",
        )
    raise InvalidConsumptionInput("O período solicitado não é reconhecido.")


def utc_bounds(period: ConsumptionPeriod) -> tuple[datetime, datetime]:
    """Converte os limites locais para UTC para consultar timestamps MongoDB."""
    return period.start.astimezone(timezone.utc), period.end.astimezone(timezone.utc)


def daily_date_bounds(period: ConsumptionPeriod) -> tuple[date, date] | None:
    """Retorna datas inclusivas para SQL diário, sem inventar horários."""
    first_day = period.start.date()
    last_day = period.last_included_date
    if last_day < first_day:
        return None
    return first_day, last_day


def _number(value: object, field_name: str) -> float:
    if isinstance(value, bool):
        raise InconsistentConsumptionData("A fonte contém um valor numérico inválido.")
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError) as exc:
        raise InconsistentConsumptionData("A fonte contém um valor numérico inválido.") from exc
    if not math.isfinite(number) or number < 0:
        raise InconsistentConsumptionData("A fonte contém valor negativo ou não finito.")
    return number


def _aggregate_daily_values(
    daily_values: dict[date, list[float]],
    *,
    last_reading_at: datetime | None = None,
    last_available_date: date | None = None,
    windows_crossing_local_midnight: int = 0,
    windows_crossing_period_end: int = 0,
) -> ConsumptionAggregate:
    daily = tuple(
        DailyConsumption(day=day, liters=math.fsum(values))
        for day, values in sorted(daily_values.items())
    )
    if not daily:
        return ConsumptionAggregate(
            daily_totals=(),
            total_liters=None,
            days_with_records=0,
            average_liters_per_recorded_day=None,
            first_recorded_date=None,
            last_recorded_date=None,
            last_reading_at=last_reading_at,
            last_available_date=last_available_date,
            missing_days_between_records=0,
            windows_crossing_local_midnight=windows_crossing_local_midnight,
            windows_crossing_period_end=windows_crossing_period_end,
        )

    total = math.fsum(item.liters for item in daily)
    first_day, last_day = daily[0].day, daily[-1].day
    recorded_dates = {item.day for item in daily}
    missing_days = sum(
        1
        for offset in range((last_day - first_day).days + 1)
        if first_day + timedelta(days=offset) not in recorded_dates
    )
    return ConsumptionAggregate(
        daily_totals=daily,
        total_liters=total,
        days_with_records=len(daily),
        average_liters_per_recorded_day=total / len(daily),
        first_recorded_date=first_day,
        last_recorded_date=last_day,
        last_reading_at=last_reading_at,
        last_available_date=last_available_date,
        missing_days_between_records=missing_days,
        windows_crossing_local_midnight=windows_crossing_local_midnight,
        windows_crossing_period_end=windows_crossing_period_end,
    )


def aggregate_windows(
    points: Iterable[ConsumptionPoint],
    *,
    period: ConsumptionPeriod,
    user_id: int,
    as_of: datetime,
) -> ConsumptionAggregate:
    """Valida janelas Mongo, deduplica identidade e soma pelo dia de início local."""
    as_of_utc = _aware_utc(as_of, "as_of")
    start_utc, end_utc = utc_bounds(period)
    zone = _zone(period.timezone_name)
    daily_values: dict[date, list[float]] = {}
    seen: dict[tuple[str, datetime, datetime], tuple[float, float | None, bool]] = {}
    last_reading_at: datetime | None = None
    crossing_count = 0
    period_end_crossing_count = 0

    for point in points:
        started = _record_aware_utc(point.window_started_at, "window_started_at")
        finished = _record_aware_utc(point.window_finished_at, "window_finished_at")
        if finished < started:
            raise InconsistentConsumptionData("Há uma janela com fim anterior ao início.")
        if point.user_id != user_id:
            raise InconsistentConsumptionData("A consulta retornou uma medição fora do usuário solicitado.")
        if started < start_utc or started >= end_utc:
            raise InconsistentConsumptionData("A consulta retornou uma medição fora do período solicitado.")
        if finished > as_of_utc:
            continue
        if not isinstance(point.device_id, str) or not point.device_id:
            raise InconsistentConsumptionData("Há uma janela sem identificador de dispositivo.")
        if not isinstance(point.anomaly_detected, bool):
            raise InconsistentConsumptionData("A fonte contém uma flag de anomalia inválida.")

        liters = _number(point.consumption_liters, "consumption_liters")
        lpm_average = (
            _number(point.lpm_average, "lpm_average")
            if point.lpm_average is not None
            else None
        )
        identity = (point.device_id, started, finished)
        values = (liters, lpm_average, bool(point.anomaly_detected))
        existing = seen.get(identity)
        if existing is not None:
            if existing != values:
                raise InconsistentConsumptionData(
                    "Há janelas repetidas com valores conflitantes no mesmo dispositivo."
                )
            continue
        seen[identity] = values

        local_start = started.astimezone(zone)
        local_finish = finished.astimezone(zone)
        if local_start.date() != local_finish.date():
            crossing_count += 1
        if finished > end_utc:
            period_end_crossing_count += 1
        daily_values.setdefault(local_start.date(), []).append(liters)
        if last_reading_at is None or finished > last_reading_at:
            last_reading_at = finished

    return _aggregate_daily_values(
        daily_values,
        last_reading_at=last_reading_at,
        windows_crossing_local_midnight=crossing_count,
        windows_crossing_period_end=period_end_crossing_count,
    )


def aggregate_daily_records(
    records: Iterable[tuple[date, object]], *, period: ConsumptionPeriod
) -> ConsumptionAggregate:
    """Agrega registros SQL diários sem convertê-los em leituras intradiárias."""
    bounds = daily_date_bounds(period)
    if bounds is None:
        return _aggregate_daily_values({})
    first_day, last_day = bounds
    daily_values: dict[date, list[float]] = {}
    for day, raw_liters in records:
        if not isinstance(day, date) or isinstance(day, datetime):
            raise InconsistentConsumptionData("A fonte diária contém uma data inválida.")
        if day < first_day or day > last_day:
            raise InconsistentConsumptionData("A fonte diária retornou data fora do período solicitado.")
        liters = _number(raw_liters, "total_liters")
        daily_values.setdefault(day, []).append(liters)

    latest_day = max(daily_values) if daily_values else None
    return _aggregate_daily_values(daily_values, last_available_date=latest_day)


def compare_aggregates(
    current: ConsumptionAggregate, previous: ConsumptionAggregate
) -> dict[str, float | None]:
    """Calcula diferença entre totais válidos; ausência não vira consumo zero."""
    if not current.has_data or not previous.has_data:
        return {"difference_liters": None, "change_percent": None}
    assert current.total_liters is not None and previous.total_liters is not None
    difference = current.total_liters - previous.total_liters
    percent = (
        difference / previous.total_liters * 100
        if previous.total_liters != 0
        else None
    )
    return {"difference_liters": difference, "change_percent": percent}


def peak_days(
    aggregate: ConsumptionAggregate, limit: int
) -> tuple[list[dict[str, str | float]], int, bool]:
    """Retorna até dez maiores totais diários; empates ordenam por data crescente."""
    validate_peak_limit(limit)
    ranked = sorted(aggregate.daily_totals, key=lambda item: (-item.liters, item.day))
    if not ranked:
        return [], 0, False
    max_liters = ranked[0].liters
    tied_for_peak = sum(item.liters == max_liters for item in ranked)
    items = [
        {"date": item.day.isoformat(), "liters": item.liters}
        for item in ranked[:limit]
    ]
    return items, tied_for_peak, len(ranked) > limit and tied_for_peak > limit


def validate_peak_limit(limit: int) -> None:
    """Valida o limite antes que a tool consulte uma fonte externa."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10:
        raise InvalidConsumptionInput("O limite de picos deve estar entre 1 e 10.")
