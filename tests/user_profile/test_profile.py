"""Perfil do usuário (residencial, comercial, sem vínculo): a mesma IA age de forma diferente."""

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from app.data import db_postgres
from app.graph import profile, router, workflow
from app.services.prompts import profile_block
from app.tools.consumption import tools as consumption_tools
from app.tools.forecast import tools as forecast_tools
from app.tools.habits import tools as habits_tools
from app.tools.models import OrganizationProperty

TODAY = date(2026, 10, 25)
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


def by_name(tools):
    return {t.name: t for t in tools}


class FakeLLM:
    """Registra o prompt de sistema e devolve a decisão de roteamento combinada."""

    def __init__(self, agents):
        self.prompts = []
        self.agents = agents

    def invoke(self, messages):
        self.prompts.append(messages[0].content)
        agents = ", ".join(f'"{name}"' for name in self.agents)
        return SimpleNamespace(
            content=f'{{"intent": "teste", "complexity": "simple", "agents": [{agents}]}}'
        )


@pytest.fixture
def llm(monkeypatch):
    fake = FakeLLM(["habits", "consumption"])
    monkeypatch.setattr("app.services.llms.llm_rapido", fake)
    return fake


# --- quais agentes cada perfil pode usar --------------------------------------------------


def test_cada_perfil_tem_o_seu_conjunto_de_agentes():
    assert "habits" in profile.allowed_agents("residential")
    assert "habits" not in profile.allowed_agents("organizational")
    assert {"consumption", "forecast", "leak", "rag"} <= profile.allowed_agents("organizational")
    assert profile.allowed_agents("none") == frozenset()
    assert profile.allowed_agents("unknown") == frozenset()
    assert profile.allowed_agents(None) is None


def test_perfil_desconhecido_nao_libera_nenhum_agente():
    assert profile.allowed_agents("qualquer-coisa") == frozenset()


def test_falha_do_banco_vira_unknown_e_nao_um_perfil_assumido(monkeypatch):
    def cai(user_id):
        raise RuntimeError("banco fora")

    monkeypatch.setattr(db_postgres, "get_user_access_kind", cai)

    assert profile.resolve_access_kind(1) == "unknown"


# --- roteador ------------------------------------------------------------------------------


def test_roteador_tira_habitos_para_conta_comercial(llm):
    decisao = router.classify("meus hábitos e consumo", {"access_kind": "organizational"})

    assert decisao.agents == ["consumption"]
    assert decisao.unavailable == ["habits"]


def test_roteador_mantem_habitos_para_conta_residencial(llm):
    decisao = router.classify("meus hábitos e consumo", {"access_kind": "residential"})

    assert decisao.agents == ["habits", "consumption"]
    assert decisao.unavailable == []


def test_roteador_sem_perfil_nao_filtra(llm):
    decisao = router.classify("meus hábitos e consumo", {})

    assert decisao.agents == ["habits", "consumption"]
    assert decisao.unavailable == []


def test_conta_sem_vinculo_fica_sem_agentes(llm):
    decisao = router.classify("meus hábitos e consumo", {"access_kind": "none"})

    assert decisao.agents == []
    assert decisao.unavailable == ["habits", "consumption"]


@pytest.mark.parametrize("perfil", ["none", "unknown"])
def test_sem_vinculo_nem_chama_o_roteador(llm, perfil):
    saida = workflow._route_node(
        {"question": "Quanto consumi esta semana?", "access_kind": perfil, "messages": []}
    )

    assert saida["selected_agents"] == []
    assert llm.prompts == []


def test_prompt_do_roteador_traz_o_perfil_e_os_agentes_disponiveis(llm):
    router.classify("oi", {"access_kind": "organizational"})

    prompt = llm.prompts[0]
    assert "comercial" in prompt
    assert "Agentes disponíveis para este usuário" in prompt
    assert "habits" not in prompt.rsplit("Agentes disponíveis para este usuário", 1)[1]


# --- respostas fixas e execução no grafo ---------------------------------------------------


def test_saudacao_muda_com_o_perfil():
    comercial = workflow._respond_node(
        {"intent": "greeting", "selected_agents": [], "access_kind": "organizational"}
    )["response"]
    residencial = workflow._respond_node(
        {"intent": "greeting", "selected_agents": [], "access_kind": "residential"}
    )["response"]

    assert "unidades" in comercial and "hábitos" not in comercial
    assert "hábitos" in residencial


def test_pedido_de_habitos_na_conta_comercial_explica_o_motivo():
    resposta = workflow._respond_node(
        {"intent": "habits", "selected_agents": [], "access_kind": "organizational",
         "unavailable_agents": ["habits"]}
    )["response"]

    assert "contas residenciais" in resposta


def test_conta_sem_vinculo_recebe_orientacao():
    resposta = workflow._respond_node(
        {"intent": "unknown", "selected_agents": [], "access_kind": "none"}
    )["response"]

    assert "ainda não está vinculada" in resposta and "Vincule" in resposta


def test_execucao_ignora_agente_que_nao_serve_ao_perfil(monkeypatch):
    executados = []
    monkeypatch.setattr(workflow, "execute_agent", lambda *a, **k: executados.append(a[0]) or {})

    saida = workflow._execute_node(
        {"question": "oi", "user_id": 1, "access_kind": "organizational",
         "selected_agents": ["habits"], "messages": []}
    )

    assert executados == []
    assert saida["agent_results"] == []
    assert any("habits" in aviso for aviso in saida["warnings"])


def test_perfil_chega_ao_agente(monkeypatch):
    recebido = {}

    def carrega(name, user_id, access_kind=None):
        recebido["access_kind"] = access_kind
        raise workflow.AgentNotImplemented(name)

    monkeypatch.setattr(workflow, "load_agent", carrega)

    workflow.execute_agent("consumption", 1, "pergunta", access_kind="organizational")

    assert recebido["access_kind"] == "organizational"


# --- prompts ---------------------------------------------------------------------------------


def test_bloco_de_prompt_por_perfil():
    assert "casa" in profile_block("residential")
    comercial = profile_block("organizational")
    assert "unidades" in comercial and "nunca de \"sua casa\"" in comercial
    assert "sem vínculo" in profile_block("none")
    assert "não identificado" in profile_block("unknown")
    assert profile_block(None) == ""


# --- tools não consultam o perfil de novo quando ele já foi resolvido ----------------------


@pytest.fixture
def no_profile_lookup(monkeypatch):
    def proibido(user_id):
        raise AssertionError("o perfil já foi resolvido na pergunta; não deve consultar de novo")

    monkeypatch.setattr(db_postgres, "get_user_access_kind", proibido)


def test_consumo_comercial_usa_o_perfil_informado(no_profile_lookup, monkeypatch):
    unidades = [OrganizationProperty(10, "Filial Alfa", "São Paulo", "SP")]
    monkeypatch.setattr(db_postgres, "get_user_organization_properties", lambda uid: unidades)
    tools = by_name(consumption_tools.build_tools(1, clock=lambda: NOW, access_kind="organizational"))

    resposta = tools["list_consumption_units"].invoke({})

    assert resposta["status"] != "insufficient_data"


def test_consumo_residencial_usa_o_perfil_informado(no_profile_lookup):
    tools = by_name(consumption_tools.build_tools(1, clock=lambda: NOW, access_kind="residential"))

    resposta = tools["list_consumption_units"].invoke({})

    assert resposta["status"] == "insufficient_data"


def test_habitos_usam_o_perfil_informado(no_profile_lookup):
    comercial = by_name(habits_tools.build_tools(1, access_kind="organizational"))

    assert comercial["list_habits"].invoke({})["status"] == "not_applicable"


def test_previsao_usa_o_perfil_informado(no_profile_lookup, monkeypatch):
    monkeypatch.setattr(db_postgres, "get_user_organization_properties", lambda uid: [])
    tools = by_name(forecast_tools.build_tools(1, TODAY, "organizational"))

    assert "check_can_estimate" in tools


def test_sem_perfil_informado_as_tools_consultam_como_antes(monkeypatch):
    calls = []
    monkeypatch.setattr(
        db_postgres, "get_user_access_kind", lambda uid: calls.append(uid) or "residential"
    )
    tools = by_name(consumption_tools.build_tools(1, clock=lambda: NOW))

    tools["list_consumption_units"].invoke({})

    assert calls == [1]
