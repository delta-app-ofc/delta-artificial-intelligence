"""Testes puros dos períodos e agregações do Agente de Consumo."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from app.tools.consumption.analysis import (
    InconsistentConsumptionData,
    InvalidConsumptionInput,
    aggregate_daily_records,
    aggregate_windows,
    compare_aggregates,
    daily_date_bounds,
    peak_days,
    resolve_period,
    utc_bounds,
)
from app.tools.models import ConsumptionPoint

UTC = timezone.utc
NOW = datetime(2026, 9, 4, 12, tzinfo=UTC)


def _point(
    start: datetime,
    liters: float,
    *,
    device_id: str = "device-a",
    user_id: int = 11,
    duration: timedelta = timedelta(minutes=5),
) -> ConsumptionPoint:
    return ConsumptionPoint(
        user_id=user_id,
        window_started_at=start,
        window_finished_at=start + duration,
        consumption_liters=liters,
        anomaly_detected=False,
        lpm_average=1.0,
        device_id=device_id,
    )


def _period(start: str = "2026-09-01", end: str = "2026-09-03"):
    return resolve_period(
        "custom", now=NOW, start_date=start, end_date=end
    )


def test_local_calendar_midnight_converts_to_utc_and_end_date_is_inclusive():
    selected = _period()
    start, end = utc_bounds(selected)

    assert start == datetime(2026, 9, 1, 3, tzinfo=UTC)
    assert end == datetime(2026, 9, 4, 3, tzinfo=UTC)
    assert selected.calendar_days == 3
    assert selected.timezone_name == "America/Sao_Paulo"


def test_named_periods_use_expected_local_boundaries_and_partial_today():
    now = datetime(2026, 9, 15, 18, 30, tzinfo=UTC)

    today = resolve_period("today", now=now)
    yesterday = resolve_period("yesterday", now=now)
    week = resolve_period("this_week", now=now)
    month = resolve_period("this_month", now=now)

    assert today.start.isoformat() == "2026-09-15T00:00:00-03:00"
    assert today.end.isoformat() == "2026-09-15T15:30:00-03:00"
    assert yesterday.start.isoformat() == "2026-09-14T00:00:00-03:00"
    assert yesterday.end.isoformat() == "2026-09-15T00:00:00-03:00"
    assert week.start.isoformat() == "2026-09-14T00:00:00-03:00"
    assert month.start.isoformat() == "2026-09-01T00:00:00-03:00"

    custom_today = resolve_period(
        "custom",
        now=now,
        start_date="2026-09-15",
        end_date="2026-09-15",
    )
    assert custom_today.end == now.astimezone(custom_today.end.tzinfo)
    assert "limitada ao instante" in custom_today.notes[0]


def test_rolling_periods_are_exact_windows_and_previous_month_matches_day_count():
    now = datetime(2026, 9, 15, 18, 30, tzinfo=UTC)
    current = resolve_period("last_7_days", now=now)
    previous = resolve_period("previous_7_days", now=now)
    previous_month = resolve_period("previous_month_same_days", now=now)

    assert (current.end.astimezone(UTC) - current.start.astimezone(UTC)) == timedelta(days=7)
    assert previous.end.astimezone(UTC) == current.start.astimezone(UTC)
    assert (previous.end.astimezone(UTC) - previous.start.astimezone(UTC)) == timedelta(days=7)
    assert previous_month.start.isoformat() == "2026-08-01T00:00:00-03:00"
    assert previous_month.end.isoformat() == "2026-08-16T00:00:00-03:00"

    march_end = resolve_period(
        "previous_month_same_days",
        now=datetime(2026, 3, 31, 12, tzinfo=UTC),
    )
    assert march_end.end.isoformat() == "2026-03-01T00:00:00-03:00"
    assert march_end.calendar_days == 28


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-09-04", "2026-09-03"),
        ("2025-08-31", "2026-09-01"),
        ("2026-09-04", "2026-09-05"),
        ("09/01/2026", "2026-09-03"),
    ],
)
def test_custom_period_rejects_inverted_future_oversized_or_malformed_dates(start, end):
    with pytest.raises(InvalidConsumptionInput):
        resolve_period("custom", now=NOW, start_date=start, end_date=end)


def test_custom_period_requires_both_dates_and_aware_reference_time():
    with pytest.raises(InvalidConsumptionInput):
        resolve_period("custom", now=NOW, start_date="2026-09-01")
    with pytest.raises(InvalidConsumptionInput):
        resolve_period("today", now=datetime(2026, 9, 4, 12))


def test_aggregation_uses_recorded_days_without_zero_filling_missing_days():
    points = [
        _point(datetime(2026, 9, 1, 12, tzinfo=UTC), 100),
        _point(datetime(2026, 9, 1, 12, tzinfo=UTC), 50, device_id="device-b"),
        _point(datetime(2026, 9, 2, 12, tzinfo=UTC), 200),
    ]

    result = aggregate_windows(points, period=_period(), user_id=11, as_of=NOW)
    peaks, tied, truncated = peak_days(result, 10)

    assert result.total_liters == 350
    assert result.days_with_records == 2
    assert result.average_liters_per_recorded_day == 175
    assert result.missing_days_between_records == 0
    assert [(item["date"], item["liters"]) for item in peaks] == [
        ("2026-09-02", 200),
        ("2026-09-01", 150),
    ]
    assert tied == 1
    assert truncated is False
    # A ausência de registro em 03/09 não cria um terceiro dia com zero.
    assert result.days_with_records != 3


def test_comparison_uses_unrounded_totals_and_expected_percentage():
    current_period = _period()
    previous_period = _period("2026-08-29", "2026-08-31")
    current = aggregate_windows(
        [
            _point(datetime(2026, 9, 1, 12, tzinfo=UTC), 100),
            _point(datetime(2026, 9, 1, 12, tzinfo=UTC), 50, device_id="device-b"),
            _point(datetime(2026, 9, 2, 12, tzinfo=UTC), 200),
        ],
        period=current_period,
        user_id=11,
        as_of=NOW,
    )
    previous = aggregate_daily_records(
        [(date(2026, 8, 31), 250)], period=previous_period
    )
    assert current.total_liters == 350
    assert compare_aggregates(current, previous) == {
        "difference_liters": 100,
        "change_percent": 40,
    }

    small_previous = aggregate_daily_records(
        [(date(2026, 8, 31), 0.004)], period=previous_period
    )
    small_current = aggregate_daily_records(
        [(date(2026, 9, 1), 0.008)], period=current_period
    )
    assert small_current.total_liters == 0.008
    assert small_current.average_liters_per_recorded_day == 0.008
    assert compare_aggregates(small_current, small_previous) == {
        "difference_liters": 0.004,
        "change_percent": 100,
    }


def test_duplicate_window_counts_once_but_conflicts_are_rejected():
    point = _point(datetime(2026, 9, 1, 12, tzinfo=UTC), 100)
    duplicate = _point(datetime(2026, 9, 1, 12, tzinfo=UTC), 100)
    result = aggregate_windows([point, duplicate], period=_period(), user_id=11, as_of=NOW)
    assert result.total_liters == 100

    conflict = _point(datetime(2026, 9, 1, 12, tzinfo=UTC), 99)
    with pytest.raises(InconsistentConsumptionData, match="conflitantes"):
        aggregate_windows([point, conflict], period=_period(), user_id=11, as_of=NOW)


@pytest.mark.parametrize("liters", [-1, float("nan"), float("inf")])
def test_negative_and_non_finite_measurements_are_rejected(liters):
    point = _point(datetime(2026, 9, 1, 12, tzinfo=UTC), liters)
    with pytest.raises(InconsistentConsumptionData):
        aggregate_windows([point], period=_period(), user_id=11, as_of=NOW)


def test_negative_daily_row_is_not_hidden_by_positive_row_for_another_unit():
    with pytest.raises(InconsistentConsumptionData):
        aggregate_daily_records(
            [
                (date(2026, 9, 1), 150),
                (date(2026, 9, 1), -1),
                (date(2026, 9, 2), 200),
            ],
            period=_period(),
        )


def test_invalid_timestamps_and_cross_midnight_windows_are_handled_explicitly():
    invalid = _point(datetime(2026, 9, 1, 12, tzinfo=UTC), 1)
    invalid = replace(
        invalid,
        window_finished_at=invalid.window_started_at - timedelta(seconds=1),
    )
    with pytest.raises(InconsistentConsumptionData, match="fim anterior"):
        aggregate_windows([invalid], period=_period(), user_id=11, as_of=NOW)

    crossing = _point(
        datetime(2026, 9, 2, 2, 58, tzinfo=UTC),
        12,
        duration=timedelta(minutes=5),
    )
    result = aggregate_windows([crossing], period=_period(), user_id=11, as_of=NOW)
    assert result.windows_crossing_local_midnight == 1
    assert result.daily_totals[0].day == date(2026, 9, 1)

    final_day = _period("2026-09-01", "2026-09-01")
    crossing_period_end = _point(
        datetime(2026, 9, 2, 2, 59, tzinfo=UTC),
        7,
        duration=timedelta(minutes=5),
    )
    edge_result = aggregate_windows(
        [crossing_period_end], period=final_day, user_id=11, as_of=NOW
    )
    assert edge_result.windows_crossing_period_end == 1


def test_unfinished_window_is_not_counted_and_wrong_user_is_inconsistent():
    now = datetime(2026, 9, 1, 13, tzinfo=UTC)
    period = resolve_period("today", now=now)
    unfinished = _point(
        datetime(2026, 9, 1, 12, 59, tzinfo=UTC),
        8,
        duration=timedelta(minutes=5),
    )
    result = aggregate_windows([unfinished], period=period, user_id=11, as_of=now)
    assert result.total_liters is None
    assert result.days_with_records == 0

    other_user = _point(datetime(2026, 9, 1, 12, tzinfo=UTC), 8, user_id=12)
    with pytest.raises(InconsistentConsumptionData, match="fora do usuário"):
        aggregate_windows([other_user], period=_period(), user_id=11, as_of=NOW)

    naive = _point(datetime(2026, 9, 1, 12, tzinfo=UTC), 1)
    naive = replace(
        naive,
        window_started_at=datetime(2026, 9, 1, 12),
        window_finished_at=datetime(2026, 9, 1, 12, 5),
    )
    with pytest.raises(InconsistentConsumptionData, match="sem fuso"):
        aggregate_windows([naive], period=_period(), user_id=11, as_of=NOW)


def test_comparison_handles_zero_base_without_division_or_false_percentage():
    period = _period()
    zero = aggregate_daily_records([(date(2026, 9, 1), 0)], period=period)
    current = aggregate_daily_records([(date(2026, 9, 2), 250)], period=period)

    assert compare_aggregates(current, zero) == {
        "difference_liters": 250,
        "change_percent": None,
    }
    assert compare_aggregates(current, aggregate_daily_records([], period=period)) == {
        "difference_liters": None,
        "change_percent": None,
    }


def test_daily_source_preserves_real_zero_and_current_date_without_faking_a_time():
    now = datetime(2026, 9, 15, 18, 30, tzinfo=UTC)
    period = resolve_period("today", now=now)
    aggregate = aggregate_daily_records([(date(2026, 9, 15), 0)], period=period)

    assert daily_date_bounds(period) == (date(2026, 9, 15), date(2026, 9, 15))
    assert aggregate.total_liters == 0
    assert aggregate.days_with_records == 1
    assert aggregate.average_liters_per_recorded_day == 0
    assert aggregate.last_available_date == date(2026, 9, 15)
    assert aggregate.last_reading_at is None


def test_peak_ties_use_date_order_and_ranking_limit_is_validated():
    period = _period()
    aggregate = aggregate_daily_records(
        [
            (date(2026, 9, 1), 100),
            (date(2026, 9, 2), 100),
            (date(2026, 9, 3), 50),
        ],
        period=period,
    )

    peaks, tied, truncated = peak_days(aggregate, 2)
    assert [item["date"] for item in peaks] == ["2026-09-01", "2026-09-02"]
    assert tied == 2
    assert truncated is False
    with pytest.raises(InvalidConsumptionInput):
        peak_days(aggregate, 11)
