"""Guarda de entrada em paralelo com contexto e roteador, e histórico lido uma única vez."""

import time
from types import SimpleNamespace

import pytest
from langgraph.graph import END

from app.graph import context as context_module
from app.graph import workflow
from app.graph.router import RoutingDecision
from app.guardrails import input as guard_input
from app.observability.diagnostics import Trace, capture

ESPERA = 0.3


def estado(**extra):
    base = {"user_id": 7, "session_id": "s1", "question": "oi", "messages": [], "_history": []}
    return {**base, **extra}


@pytest.fixture
def falsos(monkeypatch):
    """Guarda, roteador e contexto substituídos; cada um registra quando rodou e quanto demorou."""
    registro = SimpleNamespace(guarda=0, roteador=0, contexto=0, decisao_agentes=["consumption"])
    comportamento = SimpleNamespace(guarda=lambda: None, atraso_guarda=ESPERA, atraso_roteador=ESPERA)

    def guarda(pergunta):
        registro.guarda += 1
        time.sleep(comportamento.atraso_guarda)
        return comportamento.guarda()

    def roteador(pergunta, contexto):
        registro.roteador += 1
        time.sleep(comportamento.atraso_roteador)
        return RoutingDecision(intent="teste", complexity="simple", agents=registro.decisao_agentes)

    def contexto(user_id, session_id, pergunta, history=None):
        registro.contexto += 1
        return {"recent_messages": [], "relevant_memory": []}

    monkeypatch.setattr(workflow, "classify_input", guarda)
    monkeypatch.setattr(workflow, "classify", roteador)
    monkeypatch.setattr(workflow, "build_context", contexto)
    monkeypatch.setattr(workflow, "resolve_access_kind", lambda user_id: "residential")
    return SimpleNamespace(registro=registro, comportamento=comportamento)


def test_guarda_e_roteador_rodam_ao_mesmo_tempo(falsos):
    inicio = time.monotonic()
    saida = workflow._prepare_node(estado())
    duracao = time.monotonic() - inicio

    assert duracao < ESPERA * 1.8  # em série seriam 2 x ESPERA
    assert saida["selected_agents"] == ["consumption"]
    assert saida["access_kind"] == "residential"
    assert saida["_blocked"] is False


def test_guarda_bloqueia_sem_esperar_o_roteador_e_descarta_o_resultado(falsos):
    falsos.comportamento.atraso_guarda = 0.05
    falsos.comportamento.atraso_roteador = 0.8
    falsos.comportamento.guarda = lambda: {"ok": False, "reason": "Mensagem bloqueada."}

    inicio = time.monotonic()
    saida = workflow._prepare_node(estado())
    duracao = time.monotonic() - inicio

    assert duracao < 0.5
    assert saida == {"response": "Mensagem bloqueada.", "pii_map": {}, "_blocked": True}
    assert "selected_agents" not in saida


def test_bloqueio_da_guarda_encerra_o_grafo_antes_dos_agentes(falsos, monkeypatch):
    falsos.comportamento.guarda = lambda: {"ok": False, "reason": "Fora do escopo."}
    monkeypatch.setattr(workflow, "load_history_validated", lambda uid, sid: [])
    monkeypatch.setattr(
        workflow, "execute_agent", lambda *a, **k: pytest.fail("nenhum agente pode rodar após o bloqueio")
    )

    estado_final = workflow.run_workflow(7, "s1", "oi", persist_session=False)

    assert estado_final["_blocked"] is True
    assert estado_final["response"] == "Fora do escopo."


def test_rastreamento_registra_as_etapas_dos_dois_ramos(falsos):
    trace = Trace("chat", user_id=7)
    with capture(trace):
        workflow._prepare_node(estado())

    etapas = {item["stage"] for item in trace.stages}
    assert {"input_guard", "context", "router"} <= etapas
    nos = {
        evento["component"]
        for evento in trace.events
        if evento.get("event") == "graph.node.end"
    }
    assert {"guardrail_llm", "context", "route"} <= nos


def test_grafo_completo_chama_guarda_e_roteador_uma_vez_cada(falsos, monkeypatch):
    falsos.registro.decisao_agentes = []
    monkeypatch.setattr(workflow, "load_history_validated", lambda uid, sid: [])

    estado_final = workflow.run_workflow(7, "s2", "oi", persist_session=False)

    assert (falsos.registro.guarda, falsos.registro.roteador, falsos.registro.contexto) == (1, 1, 1)
    assert estado_final["_blocked"] is False
    assert "Não entendi" in estado_final["response"]


def test_apos_a_guarda_o_fluxo_segue_para_o_preparo_e_depois_para_execucao():
    assert workflow._after_guardrail_input({"_blocked": False}) == "prepare"
    assert workflow._after_guardrail_input({"_blocked": True}) == END
    assert workflow._after_prepare({"_blocked": False}) == "execute"
    assert workflow._after_prepare({"_blocked": True}) == END


# --- histórico lido uma única vez ----------------------------------------------------------


def test_historico_e_lido_uma_vez_para_o_grafo_inteiro(monkeypatch):
    leituras = []
    historico = [
        {"role": "user", "content": "oi", "sent_at": None},
        {"role": "bot", "content": "olá", "sent_at": None},
    ]
    monkeypatch.setattr(
        workflow, "load_history_validated", lambda uid, sid: leituras.append((uid, sid)) or historico
    )
    monkeypatch.setattr(
        context_module, "load_history_validated",
        lambda uid, sid: pytest.fail("o contexto não pode ler o MongoDB de novo"),
    )
    capturado = {}

    class Espia:
        checkpointer = SimpleNamespace(delete_thread=lambda thread_id: None)

        def get_state(self, config):
            return SimpleNamespace(values={})

        def invoke(self, initial, config=None):
            capturado.update(initial)
            return context_module.build_context(7, "s3", "oi", initial["_history"])

    monkeypatch.setattr(workflow, "workflow", Espia())

    workflow.run_workflow(7, "s3", "oi")

    assert leituras == [(7, "s3")]
    assert capturado["_history"] == historico
    assert [m["content"] for m in capturado["messages"]] == ["oi", "olá"]


def test_contexto_le_o_mongo_quando_nao_recebe_o_historico(monkeypatch):
    leituras = []
    monkeypatch.setattr(
        context_module, "load_history_validated", lambda uid, sid: leituras.append(sid) or []
    )

    context_module.build_context(7, "s4", "oi")
    context_module.build_context(7, "s4", "oi", history=[])

    assert leituras == ["s4"]  # só a primeira chamada leu; a segunda reaproveitou


def test_falha_na_leitura_inicial_deixa_o_contexto_tentar_e_registrar(monkeypatch):
    def falha(uid, sid):
        raise RuntimeError("mongo fora")

    monkeypatch.setattr(workflow, "load_history_validated", falha)
    capturado = {}

    class Espia:
        checkpointer = SimpleNamespace(delete_thread=lambda thread_id: None)

        def get_state(self, config):
            return SimpleNamespace(values={})

        def invoke(self, initial, config=None):
            capturado.update(initial)
            return {}

    monkeypatch.setattr(workflow, "workflow", Espia())

    workflow.run_workflow(7, "s5", "oi")

    assert capturado["_history"] is None and capturado["messages"] == []


def test_checkpoint_existente_nao_reaproveita_historico_antigo(monkeypatch):
    monkeypatch.setattr(
        workflow, "load_history_validated", lambda uid, sid: pytest.fail("não deveria ler")
    )
    capturado = {}

    class Espia:
        checkpointer = SimpleNamespace(delete_thread=lambda thread_id: None)

        def get_state(self, config):
            return SimpleNamespace(values={"messages": ["já existe"]})

        def invoke(self, initial, config=None):
            capturado.update(initial)
            return {}

    monkeypatch.setattr(workflow, "workflow", Espia())

    workflow.run_workflow(7, "s6", "oi", persist_session=False)

    assert capturado["_history"] is None  # sobrescreve qualquer valor antigo do checkpoint


# --- a função antiga continua funcionando --------------------------------------------------


def test_validate_input_compoe_regras_e_classificador(monkeypatch):
    monkeypatch.setattr(guard_input, "classify_input", lambda msg: None)
    assert guard_input.validate_input(1, "Quanto consumi?")["ok"] is True

    monkeypatch.setattr(guard_input, "classify_input", lambda msg: {"ok": False, "reason": "bloqueada"})
    assert guard_input.validate_input(1, "Quanto consumi?") == {"ok": False, "reason": "bloqueada"}


def test_regras_bloqueiam_sem_chamar_o_classificador(monkeypatch):
    monkeypatch.setattr(
        guard_input, "classify_input", lambda msg: pytest.fail("não deve chamar o LLM")
    )

    resultado = guard_input.validate_input(1, "   ")

    assert resultado == {"ok": False, "reason": "Mensagem vazia."}
