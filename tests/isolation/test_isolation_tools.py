"""Tools dos agentes: cada uma só enxerga os dados do usuário a que foi amarrada."""

from datetime import date, datetime, timezone

import pytest

from app.data import db_mongo, db_postgres
from app.tools.consumption import tools as consumption_tools
from app.tools.forecast import tools as forecast_tools
from app.tools.habits import tools as habits_tools
from app.tools.leak import tools as leak_tools
from app.tools.models import OrganizationProperty

TODAY = date(2026, 10, 25)
AGORA = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)

UNIDADES = {
    1: [OrganizationProperty(10, "Filial Alfa", "São Paulo", "SP")],
    2: [OrganizationProperty(20, "Filial Beta", "Rio de Janeiro", "RJ")],
}


def por_nome(tools):
    return {t.name: t for t in tools}


@pytest.fixture
def chamadas():
    return []


@pytest.fixture
def organizacao(monkeypatch, chamadas):
    """Dois usuários de organizações diferentes; as consultas registram quem pediu o quê."""
    monkeypatch.setattr(db_postgres, "get_user_access_kind", lambda uid: "organizational")
    monkeypatch.setattr(db_postgres, "get_user_organization_properties", lambda uid: UNIDADES.get(uid, []))

    def registra(nome, retorno):
        def funcao(*args, **kwargs):
            chamadas.append((nome, args))
            return retorno
        return funcao

    monkeypatch.setattr(db_postgres, "organization_can_estimate", registra("can_estimate", True))
    monkeypatch.setattr(db_postgres, "get_organization_consumption_history", registra("history", []))
    monkeypatch.setattr(db_postgres, "get_organization_last_billed_period", registra("last_bill", None))
    monkeypatch.setattr(db_postgres, "get_organization_effective_rate", registra("rate", None))
    monkeypatch.setattr(db_postgres, "get_organization_consumption_daily", registra("daily", []))


@pytest.fixture
def residencial(monkeypatch, chamadas):
    monkeypatch.setattr(db_postgres, "get_user_access_kind", lambda uid: "residential")

    def registra(nome, retorno):
        def funcao(*args, **kwargs):
            chamadas.append((nome, args))
            return retorno
        return funcao

    monkeypatch.setattr(db_mongo, "get_consumption_history", registra("mongo_history", []))
    monkeypatch.setattr(db_mongo, "get_anomalous_consumption_windows", registra("anomalies", []))
    monkeypatch.setattr(db_mongo, "get_alerts_history", registra("alerts", []))
    monkeypatch.setattr(db_mongo, "get_daily_liters_target", registra("target", None))
    monkeypatch.setattr(db_postgres, "get_user_habits", registra("habits", []))
    monkeypatch.setattr(db_postgres, "get_habits_by_weekday", registra("habits_day", []))


# --- user_id preso a cada conjunto de tools -------------------------------------------


@pytest.mark.parametrize("construtor", [
    lambda uid: forecast_tools.build_tools(uid, TODAY),
    leak_tools.build_tools,
    habits_tools.build_tools,
    lambda uid: consumption_tools.build_tools(uid, clock=lambda: AGORA),
], ids=["forecast", "leak", "habits", "consumption"])
@pytest.mark.parametrize("invalido", [True, False, 0, -1, "7", None, 7.0])
def test_user_id_invalido_nao_constroi_as_tools(construtor, invalido):
    with pytest.raises(ValueError):
        construtor(invalido)


def test_previsao_cada_usuario_consulta_so_as_proprias_unidades(organizacao, chamadas):
    um = por_nome(forecast_tools.build_tools(1, TODAY))
    dois = por_nome(forecast_tools.build_tools(2, TODAY))

    um["check_can_estimate"].invoke({})
    dois["check_can_estimate"].invoke({})
    um["get_last_bill"].invoke({})
    dois["get_region_rate"].invoke({})

    assert ("can_estimate", (1, [10])) in chamadas
    assert ("can_estimate", (2, [20])) in chamadas
    assert ("last_bill", (1, [10], TODAY)) in chamadas
    assert ("rate", (2, [20], TODAY)) in chamadas
    assert all(args[0] in (1, 2) and args[1] in ([10], [20]) for _, args in chamadas)


def test_previsao_unidade_de_outra_organizacao_nao_consulta_nada(organizacao, chamadas):
    tools = por_nome(forecast_tools.build_tools(1, TODAY))

    resultado = tools["check_can_estimate"].invoke({"property_name": "Filial Beta"})

    assert resultado["status"] == "insufficient_data"
    assert [u["property_id"] for u in resultado["available_units"]] == [10]
    assert chamadas == []


def test_user_id_inventado_pelo_modelo_e_ignorado(organizacao, chamadas):
    tools = por_nome(forecast_tools.build_tools(1, TODAY))

    tools["check_can_estimate"].invoke({"property_name": None, "user_id": 2})

    assert chamadas == [("can_estimate", (1, [10]))]


def test_user_id_nao_aparece_nos_argumentos_que_o_modelo_ve(residencial):
    todas = (
        forecast_tools.build_tools(1, TODAY)
        + leak_tools.build_tools(1)
        + habits_tools.build_tools(1)
        + consumption_tools.build_tools(1, clock=lambda: AGORA)
    )
    for ferramenta in todas:
        assert "user_id" not in ferramenta.args, ferramenta.name


@pytest.mark.parametrize("dias", [0, -5, 367, 10**9, True, 2.5])
def test_janela_fora_de_1_a_366_e_recusada_sem_consultar(residencial, chamadas, dias):
    previsao = por_nome(forecast_tools.build_tools(1, TODAY))
    vazamento = por_nome(leak_tools.build_tools(1))

    respostas = [
        previsao["get_consumption_history"].func(days=dias),
        previsao["calculate_forecast"].func(history_days=dias),
        vazamento["get_anomalous_windows"].func(days=dias),
        vazamento["get_alerts_history"].func(days=dias),
        vazamento["summarize_anomalous_windows"].func(days=dias),
    ]

    assert all(r["status"] == "error" for r in respostas)
    assert chamadas == []


def test_janela_valida_consulta_com_o_proprio_usuario(residencial, chamadas):
    vazamento = por_nome(leak_tools.build_tools(7))
    previsao = por_nome(forecast_tools.build_tools(7, TODAY))

    vazamento["get_anomalous_windows"].invoke({"days": 366})
    vazamento["get_alerts_history"].invoke({"days": 1})
    previsao["get_consumption_history"].invoke({"days": 30})

    assert ("anomalies", (7, 366)) in chamadas
    assert ("alerts", (7, 1)) in chamadas
    assert ("mongo_history", (7, 30)) in chamadas
    assert all(args[0] == 7 for _, args in chamadas)


def test_vazamento_cada_usuario_consulta_so_o_proprio_id(residencial, chamadas):
    por_nome(leak_tools.build_tools(1))["get_anomalous_windows"].invoke({"user_id": 2})
    por_nome(leak_tools.build_tools(2))["get_anomalous_windows"].invoke({})

    assert [args[0] for _, args in chamadas] == [1, 2]


def test_habitos_cada_usuario_consulta_so_o_proprio_id(residencial, chamadas):
    por_nome(habits_tools.build_tools(1))["list_habits"].invoke({})
    por_nome(habits_tools.build_tools(2))["get_habits_by_day"].invoke({"day": "segunda"})

    assert chamadas == [("habits", (1,)), ("habits_day", (2, "SEGUNDA"))]


def test_habitos_confere_o_vinculo_a_cada_chamada(monkeypatch, chamadas):
    vinculo = {"valor": "residential"}
    monkeypatch.setattr(db_postgres, "get_user_access_kind", lambda uid: vinculo["valor"])
    monkeypatch.setattr(db_postgres, "get_user_habits", lambda uid: chamadas.append(uid) or [])
    lista = por_nome(habits_tools.build_tools(1))["list_habits"]

    assert lista.invoke({})["status"] == "insufficient_data"
    vinculo["valor"] = "organizational"  # o vínculo mudou depois de construir as tools
    assert lista.invoke({})["status"] == "not_applicable"
    assert chamadas == [1]


def test_habito_recusado_pelo_banco_devolve_mensagem_generica(monkeypatch):
    monkeypatch.setattr(db_postgres, "get_user_access_kind", lambda uid: "residential")

    def recusa(*args, **kwargs):
        raise ValueError("Não foi possível cadastrar o hábito.")

    monkeypatch.setattr(db_postgres, "create_habit", recusa)
    criar = por_nome(habits_tools.build_tools(1))["create_habit"]

    resposta = criar.invoke({"name": "banho", "frequency": 3, "days": ["segunda"]})

    assert resposta == {"status": "error", "message": "Não foi possível cadastrar o hábito."}


# --- consumo: unidade escolhida pelo modelo precisa ser autorizada ---------------------


def test_consumo_unit_id_de_outra_organizacao_nao_consulta_nada(organizacao, chamadas):
    tools = por_nome(consumption_tools.build_tools(1, clock=lambda: AGORA))

    resultado = tools["get_consumption_summary"].invoke({"period": "last_7_days", "unit_id": 20})

    assert chamadas == []
    assert resultado["status"] != "ok"
    assert "Filial Beta" not in str(resultado)
    assert "20" not in [str(u.get("property_id")) for u in resultado.get("available_units", [])]


def test_consumo_unit_name_de_outra_organizacao_nao_consulta_nada(organizacao, chamadas):
    tools = por_nome(consumption_tools.build_tools(1, clock=lambda: AGORA))

    resultado = tools["get_consumption_summary"].invoke({"period": "last_7_days", "unit_name": "Filial Beta"})

    assert chamadas == []
    assert resultado["status"] != "ok"
    assert "Rio de Janeiro" not in str(resultado)


def test_consumo_lista_so_as_unidades_do_usuario(organizacao):
    um = por_nome(consumption_tools.build_tools(1, clock=lambda: AGORA))["list_consumption_units"].invoke({})
    dois = por_nome(consumption_tools.build_tools(2, clock=lambda: AGORA))["list_consumption_units"].invoke({})

    assert "Filial Alfa" in str(um) and "Filial Beta" not in str(um)
    assert "Filial Beta" in str(dois) and "Filial Alfa" not in str(dois)


def test_consumo_unidade_propria_consulta_so_o_id_dela(organizacao, chamadas):
    tools = por_nome(consumption_tools.build_tools(1, clock=lambda: AGORA))

    tools["get_consumption_summary"].invoke({"period": "last_7_days", "unit_id": 10})

    assert [nome for nome, _ in chamadas] == ["daily"]
    _, (user_id, property_ids, *_resto) = chamadas[0]
    assert user_id == 1 and property_ids == [10]
