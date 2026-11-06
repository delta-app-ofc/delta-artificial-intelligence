"""Ferramenta de ranking de unidades do Agente de Consumo (serviço de ranking substituído)."""

from datetime import datetime, timezone

from app.data import db_postgres
from app.tools.consumption import tools as consumption_tools
from app.tools.models import OrganizationProperty

AGORA = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
ITEMS = [
    {"propertyId": 10, "name": "Alfa", "closedDaysWithReading": 10, "consumptionLiters": 1000},
    {"propertyId": 11, "name": "Beta", "closedDaysWithReading": 10, "consumptionLiters": 3000},
    {"propertyId": 99, "name": "Alheia", "closedDaysWithReading": 10, "consumptionLiters": 9000},
]


def _rank(monkeypatch, kind="organizational", units=None, **args):
    unidades = [OrganizationProperty(10, "Alfa", "São Paulo", "SP"),
                OrganizationProperty(11, "Beta", "São Paulo", "SP")] if units is None else units
    monkeypatch.setattr(db_postgres, "get_user_organization_properties", lambda uid: unidades)
    monkeypatch.setattr(db_postgres, "get_user_organization_ids", lambda uid: [1])
    monkeypatch.setattr(consumption_tools.ranking_client, "get_organization_ranking",
                        lambda org, period: ITEMS)
    tools = {t.name: t for t in consumption_tools.build_tools(7, clock=lambda: AGORA, access_kind=kind)}
    return tools["rank_units_by_consumption"].invoke(args)


def test_ranking_ordena_so_unidades_autorizadas(monkeypatch):
    out = _rank(monkeypatch)
    assert out["status"] == "ok"
    assert out["period"] == "2026-10"
    assert [u["name"] for u in out["ranking"]] == ["Beta", "Alfa"]
    assert out["ranking"][0]["position"] == 1


def test_ranking_so_para_organizacao(monkeypatch):
    assert _rank(monkeypatch, kind="residential")["status"] == "insufficient_data"


def test_ranking_sem_unidades_autorizadas(monkeypatch):
    assert _rank(monkeypatch, units=())["status"] == "insufficient_data"


def test_ranking_rejeita_mes_invalido(monkeypatch):
    assert _rank(monkeypatch, month="10/2026")["status"] != "ok"
