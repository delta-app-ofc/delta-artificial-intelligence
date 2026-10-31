"""Progresso por SSE: plano depois do roteador e um rótulo fixo por agente e por tool."""

import pytest

from app.agents import _runtime
from app.graph import workflow
from app.observability import progress
from app.observability.progress import (
    plan_label,
    report_agent_started,
    report_tool_started,
    reset_progress_sink,
    set_progress_sink,
)


@pytest.fixture
def eventos():
    recebidos = []
    token = set_progress_sink(lambda stage, label: recebidos.append((stage, label)))
    yield recebidos
    reset_progress_sink(token)


# --- frase do plano --------------------------------------------------------------------------


@pytest.mark.parametrize("agentes, perfil, esperado", [
    (["consumption"], "residential", "Vou consultar o seu consumo"),
    (["consumption", "forecast"], "residential", "Vou consultar o seu consumo e a previsão de consumo"),
    (["consumption", "forecast", "leak"], None,
     "Vou consultar o seu consumo, a previsão de consumo e possíveis vazamentos"),
    (["consumption", "forecast"], "organizational",
     "Vou consultar o consumo das suas unidades e a previsão das suas unidades"),
    (["leak"], "organizational", "Vou consultar possíveis vazamentos"),
    (["rag"], "residential", "Vou consultar a documentação do Delta"),
    (["consumption", "consumption"], "residential", "Vou consultar o seu consumo"),
])
def test_frase_do_plano(agentes, perfil, esperado):
    assert plan_label(agentes, perfil) == esperado


def test_plano_ignora_agente_desconhecido_e_lista_vazia():
    assert plan_label([], "residential") is None
    assert plan_label(["inexistente"], "residential") is None
    assert plan_label(["inexistente", "leak"], "residential") == "Vou consultar possíveis vazamentos"


# --- rótulos de agente e de tool -------------------------------------------------------------


def test_rotulo_do_agente_depende_do_perfil(eventos):
    report_agent_started("consumption", "residential")
    report_agent_started("consumption", "organizational")
    report_agent_started("habits", "residential")

    assert eventos == [
        ("working", "Consultando o seu consumo"),
        ("working", "Consultando o consumo das suas unidades"),
        ("working", "Consultando os seus hábitos"),
    ]


def test_rotulo_de_tool_conhecida(eventos):
    report_tool_started("get_consumption_summary")
    report_tool_started("calculate_forecast")

    assert eventos == [
        ("working", "Lendo o consumo registrado"),
        ("working", "Calculando a previsão"),
    ]


def test_tool_ou_agente_desconhecido_nao_gera_evento(eventos):
    report_tool_started("unknown_tool")
    report_tool_started("ferramenta_secreta_do_banco")
    report_agent_started("agente_novo")

    assert eventos == []


def test_sem_destino_ligado_nada_acontece():
    report_tool_started("get_consumption_summary")
    report_agent_started("consumption")


def test_erro_no_destino_nao_derruba_a_pergunta():
    def quebra(stage, label):
        raise RuntimeError("fila cheia")

    token = set_progress_sink(quebra)
    try:
        report_tool_started("get_consumption_summary")
    finally:
        reset_progress_sink(token)


def test_rotulos_sao_textos_fixos_sem_parametros():
    todos = list(progress._TOOL_LABELS.values()) + list(progress._AGENT_LABELS.values())
    for rotulo in todos:
        assert "{" not in rotulo and "%" not in rotulo


# --- onde os rótulos são emitidos ------------------------------------------------------------


class FerramentaFalsa:
    def __init__(self, nome):
        self.name = nome

    def invoke(self, args):
        return {"status": "ok"}


def test_run_tool_avisa_antes_de_rodar_a_tool(eventos):
    resultado = _runtime._run_tool(FerramentaFalsa("get_consumption_summary"), "get_consumption_summary", {})

    assert resultado == {"status": "ok"}
    assert eventos == [("working", "Lendo o consumo registrado")]


def test_run_tool_com_tool_inexistente_nao_expoe_o_nome_pedido_pelo_modelo(eventos):
    _runtime._run_tool(None, "nome_inventado_pelo_modelo", {})

    assert eventos == []


def test_execute_agent_avisa_o_inicio_do_agente(eventos, monkeypatch):
    class AgenteFalso:
        def run(self, question, **kwargs):
            return type("R", (), {"response": "ok", "sources": [], "chart_data": None, "tool_calls": []})()

    monkeypatch.setattr(workflow, "load_agent", lambda name, user_id, access_kind=None: AgenteFalso())

    workflow.execute_agent("consumption", 1, "pergunta", access_kind="organizational")

    assert eventos == [("working", "Consultando o consumo das suas unidades")]


# --- integração com run_workflow_events ----------------------------------------------------------


class GrafoComProgresso:
    def __init__(self):
        self.apagados = []
        self.checkpointer = type("C", (), {"delete_thread": self.apagados.append})()

    def get_state(self, config):
        return type("S", (), {"values": {"messages": ["x"]}})()

    def stream(self, initial, config=None, stream_mode=None):
        yield ("updates", {"guardrail_input": {"question": "oi"}})
        yield ("updates", {"prepare": {"selected_agents": ["consumption"], "access_kind": "residential"}})
        report_agent_started("consumption", "residential")
        for _ in range(3):  # o modelo pediu o mesmo resumo três vezes
            report_tool_started("get_consumption_summary")
        yield ("updates", {"execute": {}})
        yield ("updates", {"compose": {}})
        yield ("values", {"response": "Resposta."})


def test_plano_e_progresso_chegam_na_ordem_e_sem_repeticao(monkeypatch):
    monkeypatch.setattr(workflow, "workflow", GrafoComProgresso())

    itens = list(workflow.run_workflow_events(7, "s1", "oi"))

    etapas = [(i["stage"], i["label"]) for i in itens if i["type"] == "stage"]
    assert etapas == [
        ("checking", "Verificando a mensagem"),
        ("understanding", "Entendendo a pergunta"),
        ("planning", "Vou consultar o seu consumo"),
        ("working", "Consultando o seu consumo"),
        ("working", "Lendo o consumo registrado"),
        ("composing", "Montando a resposta"),
        ("validating", "Validando a resposta"),
    ]
    assert itens[-1] == {"type": "final", "state": {"response": "Resposta."}}


def test_sem_agentes_escolhidos_nao_ha_plano(monkeypatch):
    class Grafo(GrafoComProgresso):
        def stream(self, initial, config=None, stream_mode=None):
            yield ("updates", {"prepare": {"selected_agents": [], "access_kind": "residential"}})
            yield ("values", {"response": "Não entendi."})

    monkeypatch.setattr(workflow, "workflow", Grafo())

    itens = list(workflow.run_workflow_events(7, "s2", "oi"))

    assert [i["stage"] for i in itens if i["type"] == "stage"] == ["checking"]


def test_o_destino_do_progresso_nao_vaza_para_depois_da_execucao(monkeypatch):
    monkeypatch.setattr(workflow, "workflow", GrafoComProgresso())
    list(workflow.run_workflow_events(7, "s3", "oi"))

    assert progress._sink.get() is None


def test_progresso_chega_de_dentro_do_grafo_real(monkeypatch):
    """Usa o LangGraph compilado de verdade; só roteador, contexto e agente são trocados."""
    from app.graph.router import RoutingDecision

    monkeypatch.setattr(workflow, "classify_input", lambda msg: None)
    monkeypatch.setattr(
        workflow, "classify",
        lambda q, ctx: RoutingDecision(intent="x", complexity="simple", agents=["consumption"]),
    )
    monkeypatch.setattr(
        workflow, "build_context", lambda *a, **k: {"recent_messages": [], "relevant_memory": []}
    )
    monkeypatch.setattr(workflow, "resolve_access_kind", lambda uid: "organizational")
    monkeypatch.setattr(workflow, "load_history_validated", lambda uid, sid: [])

    class AgenteQueFalha:
        def run(self, question, **kwargs):
            report_tool_started("get_consumption_summary")
            raise RuntimeError("falha do agente")

    monkeypatch.setattr(workflow, "load_agent", lambda name, user_id, access_kind=None: AgenteQueFalha())

    itens = list(workflow.run_workflow_events(7, "grafo-real", "oi", persist_session=False))

    etapas = [(i["stage"], i["label"]) for i in itens if i["type"] == "stage"]
    assert etapas[:5] == [
        ("checking", "Verificando a mensagem"),
        ("understanding", "Entendendo a pergunta"),
        ("planning", "Vou consultar o consumo das suas unidades"),
        ("working", "Consultando o consumo das suas unidades"),
        ("working", "Lendo o consumo registrado"),
    ]
    assert itens[-1]["type"] == "final"
