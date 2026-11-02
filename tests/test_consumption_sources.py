"""Fontes do consumo: MongoDB primeiro e, se estiver indisponível, a view diária do PostgreSQL."""

from datetime import date, datetime, timezone

import pytest

from app.data import db_mongo, db_postgres
from app.tools.consumption import tools as consumption_tools
from app.tools.exceptions import DatabaseConnectionError, DatabaseDataError
from app.tools.models import ConsumptionPoint, OrganizationProperty

AGORA = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
UNIDADES = [OrganizationProperty(10, "Filial Alfa", "São Paulo", "SP")]
FONTE_MONGO = "MongoDB consumption_summary"
FONTE_VIEW = "PostgreSQL dw.vw_ft_consumption_daily"


def janela(user_id=7, device_id="DISP-1", litros=120.0):
    inicio = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)
    fim = datetime(2026, 10, 20, 11, 0, tzinfo=timezone.utc)
    return ConsumptionPoint(user_id, inicio, fim, litros, False, None, device_id)


@pytest.fixture
def chamadas(monkeypatch):
    registro = {"mongo_usuario": 0, "mongo_dispositivos": [], "view_residencial": 0, "view_organizacional": 0}

    def view_residencial(user_id, inicio, fim):
        registro["view_residencial"] += 1
        return [(date(2026, 10, 20), 300)]

    def view_organizacional(user_id, property_ids, inicio, fim):
        registro["view_organizacional"] += 1
        return [(date(2026, 10, 20), 500)]

    monkeypatch.setattr(db_postgres, "get_user_organization_properties", lambda uid: list(UNIDADES))
    monkeypatch.setattr(db_postgres, "get_authorized_device_ids", lambda uid, ids: ["DISP-1", "DISP-2"])
    monkeypatch.setattr(db_postgres, "get_residential_consumption_daily", view_residencial)
    monkeypatch.setattr(db_postgres, "get_organization_consumption_daily", view_organizacional)
    return registro


def ferramenta(tipo):
    ferramentas = consumption_tools.build_tools(7, clock=lambda: AGORA, access_kind=tipo)
    return {t.name: t for t in ferramentas}["get_consumption_summary"]


def mongo_residencial(monkeypatch, chamadas, retorno=None, erro=None):
    def le(user_id, inicio, fim, finalizadas_ate):
        chamadas["mongo_usuario"] += 1
        if erro is not None:
            raise erro
        return retorno

    monkeypatch.setattr(db_mongo, "get_consumption_history_between", le)


def mongo_organizacional(monkeypatch, chamadas, retorno=None, erro=None):
    def le(device_ids, inicio, fim, finalizadas_ate):
        chamadas["mongo_dispositivos"].append(tuple(device_ids))
        if erro is not None:
            raise erro
        return retorno

    monkeypatch.setattr(db_mongo, "get_consumption_history_between_devices", le)


def test_residencial_usa_o_mongo_e_nao_toca_na_view(monkeypatch, chamadas):
    mongo_residencial(monkeypatch, chamadas, retorno=[janela()])

    resposta = ferramenta("residential").invoke({"period": "last_7_days"})

    assert resposta["status"] == "ok"
    assert resposta["source"] == FONTE_MONGO
    assert chamadas["view_residencial"] == 0


def test_residencial_com_mongo_fora_do_ar_cai_para_a_view(monkeypatch, chamadas):
    mongo_residencial(monkeypatch, chamadas, erro=DatabaseConnectionError("MongoDB"))

    resposta = ferramenta("residential").invoke({"period": "last_7_days"})

    assert resposta["status"] == "ok"
    assert resposta["source"] == FONTE_VIEW
    assert chamadas["view_residencial"] == 1
    assert any("MongoDB estava indisponível" in nota for nota in resposta["data_quality"]["notes"])


def test_organizacional_le_o_mongo_pelos_dispositivos_autorizados(monkeypatch, chamadas):
    # O dono gravado no documento pode faltar ou ser outro; a autorização vem dos dispositivos.
    mongo_organizacional(monkeypatch, chamadas, retorno=[janela(user_id=0, litros=80.0), janela(user_id=0, device_id="DISP-2", litros=40.0)])

    resposta = ferramenta("organizational").invoke({"period": "last_7_days"})

    assert resposta["status"] == "ok"
    assert resposta["source"] == FONTE_MONGO
    assert resposta["metrics"]["total_liters"] == 120.0
    assert chamadas["mongo_dispositivos"] == [("DISP-1", "DISP-2")]
    assert chamadas["view_organizacional"] == 0


def test_organizacional_com_mongo_fora_do_ar_cai_para_a_view(monkeypatch, chamadas):
    mongo_organizacional(monkeypatch, chamadas, erro=DatabaseConnectionError("MongoDB"))

    resposta = ferramenta("organizational").invoke({"period": "last_7_days"})

    assert resposta["status"] == "ok"
    assert resposta["source"] == FONTE_VIEW
    assert chamadas["view_organizacional"] == 1


def test_mongo_e_view_fora_do_ar_viram_fonte_indisponivel(monkeypatch, chamadas):
    mongo_residencial(monkeypatch, chamadas, erro=DatabaseConnectionError("MongoDB"))

    def view_quebrada(*args):
        raise DatabaseConnectionError("PostgreSQL")

    monkeypatch.setattr(db_postgres, "get_residential_consumption_daily", view_quebrada)

    resposta = ferramenta("residential").invoke({"period": "last_7_days"})

    assert resposta["status"] == "source_unavailable"


def test_documento_invalido_no_mongo_nao_cai_para_a_view(monkeypatch, chamadas):
    mongo_residencial(monkeypatch, chamadas, erro=DatabaseDataError("MongoDB"))

    resposta = ferramenta("residential").invoke({"period": "last_7_days"})

    assert resposta["status"] == "inconsistent_data"
    assert chamadas["view_residencial"] == 0


def test_mongo_sem_registros_nao_cai_para_a_view(monkeypatch, chamadas):
    mongo_residencial(monkeypatch, chamadas, retorno=[])

    resposta = ferramenta("residential").invoke({"period": "last_7_days"})

    assert resposta["status"] == "insufficient_data"
    assert resposta["source"] == FONTE_MONGO
    assert chamadas["view_residencial"] == 0


def test_converte_janela_sem_dono_em_ponto_do_dispositivo():
    ponto = db_mongo._to_device_point(
        {
            "device_id": "DISP-1",
            "window_started_at": datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc),
            "window_finished_at": datetime(2026, 10, 20, 11, 0, tzinfo=timezone.utc),
            "consumption_liters": 12.5,
        }
    )

    assert ponto.user_id == 0
    assert ponto.device_id == "DISP-1"
    assert ponto.consumption_liters == 12.5


def test_leitura_por_dispositivos_sem_lista_nao_consulta_o_banco():
    inicio = datetime(2026, 10, 18, tzinfo=timezone.utc)
    fim = datetime(2026, 10, 25, tzinfo=timezone.utc)

    assert db_mongo.get_consumption_history_between_devices([], inicio, fim, fim) == []
