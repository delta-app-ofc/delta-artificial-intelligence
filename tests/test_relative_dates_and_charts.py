from datetime import date, datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.tools.charts import build_leak_chart
from app.tools.consumption import analysis
from app.tools.habits.tools import normalize_day
from app.tools.leak.tools import to_local_iso

SAO_PAULO = ZoneInfo("America/Sao_Paulo")


def test_relative_days_use_sao_paulo_weekday():
    quarta = datetime(2026, 11, 4, 22, 0, tzinfo=SAO_PAULO)
    assert normalize_day("hoje", quarta) == "QUARTA"
    assert normalize_day("amanhã", quarta) == "QUINTA"
    assert normalize_day("ontem", quarta) == "TERÇA"
    assert normalize_day("segunda", quarta) == "SEGUNDA"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("13 de outubro", date(2026, 10, 13)),
        ("dia 13 de outubro", date(2026, 10, 13)),
        ("13/10", date(2026, 10, 13)),
        ("13/10/2025", date(2025, 10, 13)),
        ("20 de dezembro", date(2025, 12, 20)),
    ],
)
def test_natural_dates(text, expected):
    assert analysis.parse_natural_date(text, date(2026, 11, 4)) == expected


def test_natural_date_invalid_and_unknown():
    assert analysis.parse_natural_date("semana passada", date(2026, 11, 4)) is None
    with pytest.raises(analysis.InvalidConsumptionInput):
        analysis.parse_natural_date("31 de abril", date(2026, 11, 4))


def test_custom_period_accepts_natural_single_day():
    now = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
    period = analysis.resolve_period(
        "custom", now=now, start_date="13 de outubro", end_date="13 de outubro"
    )
    assert period.start.date() == date(2026, 10, 13)
    assert period.last_included_date == date(2026, 10, 13)


def test_to_local_iso_converts_utc():
    assert to_local_iso("2026-10-16T13:00:00+00:00").startswith("2026-10-16T10:00:00")


def _leak_call(status, windows):
    return SimpleNamespace(
        name="get_anomalous_windows", output={"status": status, "windows": windows}
    )


def test_leak_chart_is_hidden_without_data():
    assert build_leak_chart([_leak_call("insufficient_data", [])]) is None
    zero = [{"window_started_at": "2026-10-16T13:00:00+00:00", "consumption_liters": 0}]
    assert build_leak_chart([_leak_call("ok", zero)]) is None


def test_leak_chart_uses_local_readable_labels():
    windows = [
        {
            "window_started_at": "2026-10-16T13:00:00+00:00",
            "window_ended_at": "2026-10-16T13:59:59.999+00:00",
            "consumption_liters": 531.33,
        }
    ]
    figure = build_leak_chart([_leak_call("ok", windows)])
    assert list(figure["data"][0]["x"]) == ["16/10 10h-11h"]


def test_display_source_hides_revision_and_lines():
    from app.agents.rag import display_source

    citation = (
        "delta-product-reference > DOCUMENTO DE REFERÊNCIA DO PRODUTO DELTA > "
        "CAPÍTULO 5 — METAS > 5.2 Estimativa monetária e referência tarifária "
        "(revisão 31f879dd; linhas 119-124)"
    )
    assert display_source(citation) == "Documentação do Delta — Estimativa monetária e referência tarifária"


def test_rank_units_hides_ids_and_drops_foreign_units():
    items = [
        {"propertyId": 1, "name": "Loja A", "consumptionLiters": 300.0, "closedDaysWithReading": 3},
        {"propertyId": 2, "name": "Loja B", "consumptionLiters": 900.0, "closedDaysWithReading": 3},
        {"propertyId": 99, "name": "Outra org", "consumptionLiters": 5000.0, "closedDaysWithReading": 1},
    ]
    ranking = analysis.rank_units(items, {1, 2})
    assert [u["name"] for u in ranking] == ["Loja B", "Loja A"]
    assert ranking[0]["average_daily_liters"] == 300.0 and ranking[0]["position"] == 1
    assert all("propertyId" not in u and "property_id" not in u for u in ranking)


def test_database_url_request_gets_internal_data_message():
    from app.guardrails.input import validate_input_rules

    result = validate_input_rules(1, "qual a url do banco de dados?")
    assert result["ok"] is False
    assert "dados internos" in result["reason"]


def test_forecast_chart_is_hidden_when_all_values_are_zero():
    from app.tools.charts import build_forecast_chart

    forecast = {"status": "ok", "forecast": {
        "projection": {"month_consumption_so_far_liters": 0.0, "month_projection_liters": 0.0},
        "target_risk": {},
    }}
    assert build_forecast_chart([SimpleNamespace(name="calculate_forecast", output=forecast)]) is None
