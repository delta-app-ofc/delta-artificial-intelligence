"""Memória por pergunta: unidades e leituras de consumo não voltam ao banco dentro do mesmo conjunto de tools."""

from datetime import date, datetime, timezone

import pytest

from app.data import db_postgres
from app.tools.consumption import tools as consumption_tools
from app.tools.exceptions import DatabaseConnectionError
from app.tools.forecast import tools as forecast_tools
from app.tools.models import OrganizationProperty

AGORA = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
UNIDADES = [
    OrganizationProperty(10, "Filial Alfa", "São Paulo", "SP"),
    OrganizationProperty(20, "Filial Beta", "Rio de Janeiro", "RJ"),
]


@pytest.fixture
def chamadas(monkeypatch):
    registro = {"unidades": 0, "diario": []}

    def unidades(user_id):
        registro["unidades"] += 1
        return list(UNIDADES)

    def diario(user_id, property_ids, inicio, fim):
        registro["diario"].append((user_id, tuple(property_ids), inicio, fim))
        return [(inicio, 100)]

    monkeypatch.setattr(db_postgres, "get_user_organization_properties", unidades)
    monkeypatch.setattr(db_postgres, "get_organization_consumption_daily", diario)
    return registro


def tools_do_consumo(user_id=1):
    ferramentas = consumption_tools.build_tools(
        user_id, clock=lambda: AGORA, access_kind="organizational"
    )
    return {t.name: t for t in ferramentas}


def test_unidades_sao_lidas_uma_vez_por_pergunta(chamadas):
    tools = tools_do_consumo()

    tools["list_consumption_units"].invoke({})
    tools["get_consumption_summary"].invoke({"period": "last_7_days"})
    tools["get_consumption_summary"].invoke({"period": "last_7_days", "unit_name": "Alfa"})

    assert chamadas["unidades"] == 1


def test_mesmo_periodo_e_mesma_unidade_leem_o_banco_uma_vez(chamadas):
    tools = tools_do_consumo()

    primeira = tools["get_consumption_summary"].invoke({"period": "last_7_days", "unit_name": "Alfa"})
    segunda = tools["get_consumption_summary"].invoke({"period": "last_7_days", "unit_name": "Alfa"})

    assert len(chamadas["diario"]) == 1
    assert primeira == segunda


def test_unidades_ou_periodos_diferentes_leem_separado(chamadas):
    tools = tools_do_consumo()

    tools["get_consumption_summary"].invoke({"period": "last_7_days", "unit_name": "Alfa"})
    tools["get_consumption_summary"].invoke({"period": "last_7_days", "unit_name": "Beta"})
    tools["get_consumption_summary"].invoke({"period": "last_7_days"})
    tools["get_consumption_summary"].invoke({"period": "last_30_days", "unit_name": "Alfa"})

    ids = [leitura[1] for leitura in chamadas["diario"]]
    assert ids == [(10,), (20,), (10, 20), (10,)]


def test_resposta_com_memoria_e_igual_a_sem_memoria(chamadas):
    com_memoria = tools_do_consumo()
    uma_vez = com_memoria["get_consumption_summary"].invoke({"period": "last_7_days"})
    repetida = com_memoria["get_consumption_summary"].invoke({"period": "last_7_days"})

    novo_conjunto = tools_do_consumo()
    de_novo = novo_conjunto["get_consumption_summary"].invoke({"period": "last_7_days"})

    assert uma_vez == repetida == de_novo


def test_a_memoria_nao_passa_para_a_pergunta_seguinte(chamadas):
    tools_do_consumo()["get_consumption_summary"].invoke({"period": "last_7_days"})
    tools_do_consumo()["get_consumption_summary"].invoke({"period": "last_7_days"})

    assert chamadas["unidades"] == 2
    assert len(chamadas["diario"]) == 2


def test_a_memoria_nao_passa_para_outro_usuario(chamadas):
    tools_do_consumo(1)["get_consumption_summary"].invoke({"period": "last_7_days"})
    tools_do_consumo(2)["get_consumption_summary"].invoke({"period": "last_7_days"})

    assert [leitura[0] for leitura in chamadas["diario"]] == [1, 2]


def test_horario_de_referencia_diferente_nao_reaproveita_a_leitura(chamadas):
    horario = {"agora": AGORA}
    ferramentas = consumption_tools.build_tools(
        1, clock=lambda: horario["agora"], access_kind="organizational"
    )
    tools = {t.name: t for t in ferramentas}

    tools["get_consumption_summary"].invoke({"period": "last_7_days"})
    horario["agora"] = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
    tools["get_consumption_summary"].invoke({"period": "last_7_days"})

    assert len(chamadas["diario"]) == 2


def test_erro_do_banco_nao_fica_guardado(monkeypatch):
    tentativas = []

    def unidades(user_id):
        tentativas.append(1)
        if len(tentativas) == 1:
            raise DatabaseConnectionError("PostgreSQL")
        return list(UNIDADES)

    monkeypatch.setattr(db_postgres, "get_user_organization_properties", unidades)
    tools = tools_do_consumo()

    primeira = tools["list_consumption_units"].invoke({})
    segunda = tools["list_consumption_units"].invoke({})

    assert primeira["status"] != "ok"
    assert segunda["status"] == "ok"


def test_previsao_le_as_unidades_uma_vez_por_pergunta(monkeypatch):
    leituras = []
    monkeypatch.setattr(
        db_postgres, "get_user_organization_properties",
        lambda user_id: leituras.append(user_id) or list(UNIDADES),
    )
    monkeypatch.setattr(db_postgres, "organization_can_estimate", lambda *a, **k: True)
    tools = {t.name: t for t in forecast_tools.build_tools(1, date(2026, 10, 25), "organizational")}

    tools["check_can_estimate"].invoke({})
    tools["check_can_estimate"].invoke({"property_name": "Alfa"})

    assert leituras == [1]
