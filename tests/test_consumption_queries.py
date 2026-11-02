"""Consultas novas do consumo (PostgreSQL e MongoDB) e o limite do fallback."""

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

import pytest

from app.data import db_mongo, db_postgres
from app.tools.consumption import tools as consumption_tools
from app.tools.exceptions import DatabaseConnectionError
from app.tools.forecast import tools as forecast_tools
from app.tools.models import OrganizationProperty

AGORA = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
UTC = timezone.utc


class CursorFalso:
    def __init__(self, linhas):
        self.linhas = linhas
        self.executado = []

    def execute(self, sql, params=None):
        self.executado.append((sql, params))

    def fetchall(self):
        return self.linhas


@pytest.fixture
def cursor(monkeypatch):
    def usa(linhas):
        falso = CursorFalso(linhas)

        @contextmanager
        def fake():
            yield falso

        monkeypatch.setattr(db_postgres, "_cursor", fake)
        return falso

    return usa


def test_dispositivos_autorizados_usam_a_funcao_de_autorizacao(cursor):
    falso = cursor([("DISP-1",), ("DISP-2",)])

    assert db_postgres.get_authorized_device_ids(7, [10, 20]) == ["DISP-1", "DISP-2"]

    sql, params = falso.executado[0]
    assert "fn_user_authorized_property_ids" in sql and "tb_device" in sql
    assert params == (7, [10, 20])


def test_dispositivos_sem_unidades_nao_consultam_o_banco(cursor):
    falso = cursor([("X",)])

    assert db_postgres.get_authorized_device_ids(7, []) == []
    assert falso.executado == []


def test_consumo_residencial_diario_filtra_pelos_imoveis_do_usuario(cursor):
    falso = cursor([(date(2026, 10, 20), 300)])

    linhas = db_postgres.get_residential_consumption_daily(7, date(2026, 10, 18), date(2026, 10, 25))

    assert linhas == [(date(2026, 10, 20), 300)]
    sql, params = falso.executado[0]
    assert "tb_user_property" in sql and "dw.vw_ft_consumption_daily" in sql
    assert params == (7, date(2026, 10, 18), date(2026, 10, 25))


def test_consumo_residencial_diario_rejeita_datas_invalidas(cursor):
    cursor([])

    with pytest.raises(ValueError):
        db_postgres.get_residential_consumption_daily(7, datetime(2026, 10, 18), date(2026, 10, 25))
    with pytest.raises(ValueError):
        db_postgres.get_residential_consumption_daily(7, date(2026, 10, 25), date(2026, 10, 18))


def test_historico_residencial_vira_pontos_diarios(cursor):
    falso = cursor([(date(2026, 10, 20), 900), (date(2026, 10, 21), 450)])

    pontos = db_postgres.get_residential_consumption_history(7, 14, date(2026, 10, 25))

    assert [p.consumption_liters for p in pontos] == [900.0, 450.0]
    assert pontos[0].window_finished_at - pontos[0].window_started_at == timedelta(days=1)
    assert falso.executado[0][1] == (7, date(2026, 10, 25), 14, date(2026, 10, 25))


@pytest.fixture
def leitor_mongo(monkeypatch):
    capturado = {}

    def le(component, collection, query, sort_field, sort_direction, converter):
        capturado.update(component=component, collection=collection, query=query, converter=converter)
        return []

    monkeypatch.setattr(db_mongo, "_read_many", le)
    return capturado


def test_mongo_por_dispositivos_consulta_so_os_dispositivos_informados(leitor_mongo):
    inicio, fim = datetime(2026, 10, 18, tzinfo=UTC), datetime(2026, 10, 25, tzinfo=UTC)

    db_mongo.get_consumption_history_between_devices(["D1", "D2"], inicio, fim, fim)

    assert leitor_mongo["query"]["device_id"] == {"$in": ["D1", "D2"]}
    assert leitor_mongo["query"]["window_started_at"] == {"$gte": inicio, "$lt": fim}
    assert leitor_mongo["query"]["window_finished_at"] == {"$lte": fim}
    assert "user_id" not in leitor_mongo["query"]


def test_mongo_por_dispositivos_valida_os_limites(leitor_mongo):
    inicio, fim = datetime(2026, 10, 18, tzinfo=UTC), datetime(2026, 10, 25, tzinfo=UTC)

    with pytest.raises(ValueError):
        db_mongo.get_consumption_history_between_devices(["D1"], datetime(2026, 10, 18), fim, fim)
    with pytest.raises(ValueError):
        db_mongo.get_consumption_history_between_devices(["D1"], fim, inicio, fim)
    assert leitor_mongo == {}


def test_historico_por_dispositivos_usa_a_janela_em_dias(leitor_mongo):
    db_mongo.get_consumption_history_by_devices(["D1"], 7)

    consulta = leitor_mongo["query"]
    assert consulta["device_id"] == {"$in": ["D1"]}
    assert datetime.now(UTC) - consulta["window_started_at"]["$gte"] > timedelta(days=6, hours=23)


def test_historico_por_dispositivos_sem_lista_nao_consulta(leitor_mongo):
    assert db_mongo.get_consumption_history_by_devices([], 7) == []
    assert leitor_mongo == {}


def test_falha_do_postgres_na_autorizacao_nao_vira_leitura_da_view_no_consumo(monkeypatch):
    chamadas = []
    monkeypatch.setattr(db_postgres, "get_user_organization_properties",
                        lambda uid: [OrganizationProperty(10, "Filial Alfa", "São Paulo", "SP")])

    def quebra(uid, ids):
        raise DatabaseConnectionError("PostgreSQL")

    monkeypatch.setattr(db_postgres, "get_authorized_device_ids", quebra)
    monkeypatch.setattr(db_postgres, "get_organization_consumption_daily",
                        lambda *a: chamadas.append("view") or [])
    tools = {t.name: t for t in consumption_tools.build_tools(7, clock=lambda: AGORA, access_kind="organizational")}

    resposta = tools["get_consumption_summary"].invoke({"period": "last_7_days"})

    assert resposta["status"] == "source_unavailable"
    assert chamadas == []


def test_falha_do_postgres_na_autorizacao_nao_vira_leitura_da_view_na_previsao(monkeypatch):
    chamadas = []
    monkeypatch.setattr(db_postgres, "get_user_organization_properties",
                        lambda uid: [OrganizationProperty(10, "Filial Alfa", "São Paulo", "SP")])

    def quebra(uid, ids):
        raise DatabaseConnectionError("PostgreSQL")

    monkeypatch.setattr(db_postgres, "get_authorized_device_ids", quebra)
    monkeypatch.setattr(db_postgres, "get_organization_consumption_history",
                        lambda *a: chamadas.append("view") or [])
    tools = {t.name: t for t in forecast_tools.build_tools(7, date(2026, 10, 25), access_kind="organizational")}

    with pytest.raises(DatabaseConnectionError):
        tools["get_consumption_history"].invoke({"days": 7})

    assert chamadas == []
