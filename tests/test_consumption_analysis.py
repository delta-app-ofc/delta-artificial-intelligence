from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.tools.consumption.analysis import (
    InconsistentConsumptionData,
    InvalidConsumptionInput,
    aggregate_daily_records,
    aggregate_windows,
    compare_aggregates,
    peak_days,
    resolve_period,
    utc_bounds,
)
from app.tools.models import ConsumptionPoint


ZONE_NAME = "America/Sao_Paulo"
ZONE = ZoneInfo(ZONE_NAME)


def _local(day, hour, minute=0):
    return datetime.combine(day, time(hour, minute), tzinfo=ZONE)


def _point(start, finish, liters, *, user_id=4, device="meter-1"):
    return ConsumptionPoint(
        user_id=user_id,
        window_started_at=start.astimezone(timezone.utc),
        window_finished_at=finish.astimezone(timezone.utc),
        consumption_liters=liters,
        anomaly_detected=False,
        lpm_average=liters / 5,
        device_id=device,
    )


def _period(start, end, now=None):
    return resolve_period(
        "custom",
        now=now or datetime(2026, 3, 3, 15, tzinfo=timezone.utc),
        timezone_name=ZONE_NAME,
        start_date=start,
        end_date=end,
    )


def test_custom_period_uses_local_inclusive_dates_and_utc_half_open_bounds():
    period = _period("2026-02-28", "2026-03-01")

    assert period.start == _local(date(2026, 2, 28), 0)
    assert period.end == _local(date(2026, 3, 2), 0)
    assert period.calendar_days == 2
    assert period.last_included_date == date(2026, 3, 1)
    start_utc, end_utc = utc_bounds(period)
    assert start_utc.utcoffset() == timedelta(0)
    assert end_utc - start_utc == timedelta(days=2)


@pytest.mark.parametrize(
    ("period", "values"),
    [
        ("custom", {"start_date": "2026-03-02", "end_date": "2026-03-01"}),
        ("custom", {"start_date": "2026-02-30", "end_date": "2026-03-01"}),
        ("custom", {"start_date": "2025-01-01", "end_date": "2026-01-02"}),
        ("today", {"start_date": "2026-03-01"}),
    ],
)
def test_period_rejects_reversed_invalid_overlong_or_misnamed_dates(period, values):
    with pytest.raises(InvalidConsumptionInput):
        resolve_period(
            period,
            now=datetime(2026, 3, 3, 15, tzinfo=timezone.utc),
            timezone_name=ZONE_NAME,
            **values,
        )


def test_custom_period_caps_today_at_query_time():
    now = datetime(2026, 3, 2, 15, tzinfo=timezone.utc)
    period = _period("2026-03-02", "2026-03-02", now=now)

    assert period.end == now.astimezone(ZONE)
    assert period.notes == ("A data final de hoje foi limitada ao instante da consulta.",)


def test_window_aggregation_deduplicates_cross_midnight_records_and_skips_open_windows():
    period = _period("2026-02-28", "2026-03-01")
    as_of = _local(date(2026, 3, 2), 12)
    first = _point(
        _local(date(2026, 2, 28), 23, 58),
        _local(date(2026, 3, 1), 0, 3),
        4.0,
    )
    final = _point(
        _local(date(2026, 3, 1), 23, 58),
        _local(date(2026, 3, 2), 0, 3),
        10.0,
    )
    still_open = _point(
        _local(date(2026, 3, 1), 12),
        _local(date(2026, 3, 2), 13),
        99.0,
    )

    result = aggregate_windows(
        [first, first, final, still_open],
        period=period,
        user_id=4,
        as_of=as_of,
    )

    assert [(item.day, item.liters) for item in result.daily_totals] == [
        (date(2026, 2, 28), 4.0),
        (date(2026, 3, 1), 10.0),
    ]
    assert result.total_liters == 14.0
    assert result.average_liters_per_recorded_day == 7.0
    assert result.windows_crossing_local_midnight == 2
    assert result.windows_crossing_period_end == 1
    assert result.last_reading_at == final.window_finished_at


def test_conflicting_duplicate_or_wrong_user_window_is_rejected():
    period = _period("2026-02-28", "2026-03-01")
    start = _local(date(2026, 2, 28), 8)
    first = _point(start, start + timedelta(minutes=5), 2.0)
    conflicting = _point(start, start + timedelta(minutes=5), 3.0)
    as_of = _local(date(2026, 3, 2), 12)

    with pytest.raises(InconsistentConsumptionData, match="conflitantes"):
        aggregate_windows(
            [first, conflicting],
            period=period,
            user_id=4,
            as_of=as_of,
        )
    with pytest.raises(InconsistentConsumptionData, match="fora do usuário"):
        aggregate_windows(
            [_point(start, start + timedelta(minutes=5), 2.0, user_id=5)],
            period=period,
            user_id=4,
            as_of=as_of,
        )


def test_daily_aggregation_preserves_zero_and_reports_gaps_without_inventing_days():
    period = _period("2026-02-28", "2026-03-02")

    result = aggregate_daily_records(
        [(date(2026, 2, 28), 0), (date(2026, 3, 2), 5)],
        period=period,
    )

    assert result.has_data is True
    assert result.total_liters == 5.0
    assert result.days_with_records == 2
    assert result.average_liters_per_recorded_day == 2.5
    assert result.daily_totals[0].liters == 0.0
    assert result.missing_days_between_records == 1
    assert result.has_gaps_between_recorded_days is True


def test_comparison_with_zero_previous_total_has_no_percentage():
    period = _period("2026-02-28", "2026-03-02")
    current = aggregate_daily_records([(date(2026, 3, 2), 5)], period=period)
    previous = aggregate_daily_records([(date(2026, 2, 28), 0)], period=period)

    assert compare_aggregates(current, previous) == {
        "difference_liters": 5.0,
        "change_percent": None,
    }


def test_peak_days_order_ties_by_date_and_reports_truncated_ties():
    period = _period("2026-02-28", "2026-03-02")
    aggregate = aggregate_daily_records(
        [
            (date(2026, 3, 2), 5),
            (date(2026, 2, 28), 5),
            (date(2026, 3, 1), 1),
        ],
        period=period,
    )

    items, tied, truncated = peak_days(aggregate, limit=1)

    assert items == [{"date": "2026-02-28", "liters": 5.0}]
    assert tied == 2
    assert truncated is True
    with pytest.raises(InvalidConsumptionInput):
        peak_days(aggregate, limit=0)
