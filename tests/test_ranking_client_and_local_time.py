"""Cliente do ranking (HTTP substituído) e conversão de horários do Agente de Vazamento."""

from types import SimpleNamespace

import httpx
import pytest

from app.config import ConfigurationError
from app.data import ranking_client
from app.tools.exceptions import DatabaseAccessError
from app.tools.leak.tools import _with_local_times, to_local_iso


def _settings(monkeypatch, url):
    monkeypatch.setattr(ranking_client, "get_settings", lambda: SimpleNamespace(ranking_service_url=url))


def _response(monkeypatch, body=None, status=200):
    request = httpx.Request("GET", "http://ranking/get-ranking")
    monkeypatch.setattr(
        ranking_client.httpx, "get",
        lambda *a, **k: httpx.Response(status, json=body, request=request),
    )


def test_ranking_exige_url_configurada(monkeypatch):
    _settings(monkeypatch, "")
    with pytest.raises(ConfigurationError):
        ranking_client.get_organization_ranking(1, "2026-10")


def test_ranking_devolve_itens(monkeypatch):
    _settings(monkeypatch, "http://ranking")
    _response(monkeypatch, {"items": [{"propertyId": 1}]})
    assert ranking_client.get_organization_ranking(1, "2026-10") == [{"propertyId": 1}]


def test_ranking_sem_lista_devolve_vazio(monkeypatch):
    _settings(monkeypatch, "http://ranking")
    _response(monkeypatch, {"items": None})
    assert ranking_client.get_organization_ranking(1, "2026-10") == []


def test_ranking_erro_http_vira_erro_de_banco(monkeypatch):
    _settings(monkeypatch, "http://ranking")
    _response(monkeypatch, {}, status=500)
    with pytest.raises(DatabaseAccessError):
        ranking_client.get_organization_ranking(1, "2026-10")


def test_horario_utc_vira_brasilia():
    assert to_local_iso("2026-11-05T15:00:00Z".replace("Z", "+00:00")) == "2026-11-05T12:00:00-03:00"
    assert to_local_iso("2026-11-05T15:00:00") == "2026-11-05T12:00:00-03:00"


def test_horario_invalido_devolve_none():
    assert to_local_iso("não é data") is None
    assert to_local_iso(None) is None


def test_item_ganha_campos_locais_so_quando_validos():
    item = {"triggered_at": "2026-11-05T15:00:00", "resolved_at": "ruim", "outro": 1}
    result = _with_local_times(item)
    assert result["triggered_at_local"] == "2026-11-05T12:00:00-03:00"
    assert "resolved_at_local" not in result
    assert "triggered_at_local" not in item
