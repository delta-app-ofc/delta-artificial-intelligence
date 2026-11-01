"""Histórico da previsão: MongoDB primeiro e, se estiver indisponível, a view diária do PostgreSQL."""

from datetime import date, datetime, timezone

import pytest

from app.data import db_mongo, db_postgres
from app.tools.exceptions import DatabaseConnectionError, DatabaseDataError
from app.tools.forecast import tools as forecast_tools
from app.tools.models import ConsumptionPoint, OrganizationProperty

HOJE = date(2026, 10, 25)
UNIDADES = [OrganizationProperty(10, "Filial Alfa", "São Paulo", "SP")]


def ponto(user_id=7, device_id="DISP-1", litros=50.0):
    inicio = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)
    fim = datetime(2026, 10, 20, 11, 0, tzinfo=timezone.utc)
    return ConsumptionPoint(user_id, inicio, fim, litros, False, None, device_id)


def ponto_diario(litros=900.0):
    inicio = datetime(2026, 10, 20)
    return ConsumptionPoint(0, inicio, datetime(2026, 10, 21), litros, False, None, None)


@pytest.fixture
def chamadas(monkeypatch):
    registro = {"mongo_usuario": 0, "mongo_dispositivos": [], "view_residencial": 0, "view_organizacional": 0}

    def view_residencial(user_id, days, today):
        registro["view_residencial"] += 1
        return [ponto_diario(900.0)]

    def view_organizacional(user_id, ids, days, today):
        registro["view_organizacional"] += 1
        return [ponto_diario(1500.0)]

    monkeypatch.setattr(db_postgres, "get_user_organization_properties", lambda uid: list(UNIDADES))
    monkeypatch.setattr(db_postgres, "get_authorized_device_ids", lambda uid, ids: ["DISP-1", "DISP-2"])
    monkeypatch.setattr(db_postgres, "get_residential_consumption_history", view_residencial)
    monkeypatch.setattr(db_postgres, "get_organization_consumption_history", view_organizacional)
    return registro


def historico(tipo):
    ferramentas = forecast_tools.build_tools(7, HOJE, access_kind=tipo)
    return {t.name: t for t in ferramentas}["get_consumption_history"]


def mongo_usuario(monkeypatch, chamadas, retorno=None, erro=None):
    def le(user_id, days):
        chamadas["mongo_usuario"] += 1
        if erro is not None:
            raise erro
        return retorno

    monkeypatch.setattr(db_mongo, "get_consumption_history", le)


def mongo_dispositivos(monkeypatch, chamadas, retorno=None, erro=None):
    def le(device_ids, days):
        chamadas["mongo_dispositivos"].append(tuple(device_ids))
        if erro is not None:
            raise erro
        return retorno

    monkeypatch.setattr(db_mongo, "get_consumption_history_by_devices", le)


def test_residencial_usa_o_mongo(monkeypatch, chamadas):
    mongo_usuario(monkeypatch, chamadas, retorno=[ponto()])

    resposta = historico("residential").invoke({"days": 7})

    assert resposta["status"] == "ok"
    assert resposta["windows"][0]["consumption_liters"] == 50.0
    assert chamadas["view_residencial"] == 0


def test_residencial_com_mongo_fora_do_ar_usa_a_view(monkeypatch, chamadas):
    mongo_usuario(monkeypatch, chamadas, erro=DatabaseConnectionError("MongoDB"))

    resposta = historico("residential").invoke({"days": 7})

    assert resposta["status"] == "ok"
    assert resposta["windows"][0]["consumption_liters"] == 900.0
    assert chamadas["view_residencial"] == 1


def test_organizacional_le_o_mongo_pelos_dispositivos_autorizados(monkeypatch, chamadas):
    mongo_dispositivos(monkeypatch, chamadas, retorno=[ponto(user_id=0, litros=30.0)])

    resposta = historico("organizational").invoke({"days": 7})

    assert resposta["status"] == "ok"
    assert resposta["windows"][0]["consumption_liters"] == 30.0
    assert chamadas["mongo_dispositivos"] == [("DISP-1", "DISP-2")]
    assert chamadas["view_organizacional"] == 0


def test_organizacional_com_mongo_fora_do_ar_usa_a_view(monkeypatch, chamadas):
    mongo_dispositivos(monkeypatch, chamadas, erro=DatabaseConnectionError("MongoDB"))

    resposta = historico("organizational").invoke({"days": 7})

    assert resposta["windows"][0]["consumption_liters"] == 1500.0
    assert chamadas["view_organizacional"] == 1


def test_documento_invalido_no_mongo_nao_troca_de_fonte(monkeypatch, chamadas):
    mongo_usuario(monkeypatch, chamadas, erro=DatabaseDataError("MongoDB"))

    with pytest.raises(DatabaseDataError):
        historico("residential").invoke({"days": 7})

    assert chamadas["view_residencial"] == 0


def test_mongo_sem_registros_nao_troca_de_fonte(monkeypatch, chamadas):
    mongo_usuario(monkeypatch, chamadas, retorno=[])

    resposta = historico("residential").invoke({"days": 7})

    assert resposta["status"] == "insufficient_data"
    assert chamadas["view_residencial"] == 0
