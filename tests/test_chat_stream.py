"""POST /chat/stream: etapas por SSE, resposta só no fim, mesmos códigos HTTP do /chat antes de abrir o fluxo."""

import json
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.graph import workflow
from app.memory import session as memory
from app.routes import chat as chat_route
from tests.conftest import JWT_SECRET, auth_header

RESPOSTA = "Você consumiu 120 litros."


def eventos_sse(texto: str) -> list[tuple[str, dict]]:
    """Lê o corpo SSE em [(evento, dados)]; comentários (keep-alive) viram ("comment", {})."""
    lidos = []
    for bloco in texto.strip().split("\n\n"):
        if not bloco.strip():
            continue
        if bloco.startswith(":"):
            lidos.append(("comment", {}))
            continue
        linhas = dict(linha.split(": ", 1) for linha in bloco.splitlines())
        lidos.append((linhas["event"], json.loads(linhas["data"])))
    return lidos


@pytest.fixture
def client(mongo_db, monkeypatch):
    monkeypatch.setattr("app.auth.get_settings", lambda: SimpleNamespace(jwt_secret=JWT_SECRET))
    app = FastAPI()
    app.include_router(chat_route.router)
    return TestClient(app)


def usa_eventos(monkeypatch, itens):
    chamadas = []

    def falso(user_id, session_id, question, **kwargs):
        chamadas.append((user_id, session_id, question))
        yield from itens

    monkeypatch.setattr(chat_route, "run_workflow_events", falso)
    return chamadas


def post(client, user_id=7, **corpo):
    return client.post(
        "/chat/stream", json={"message": "Quanto consumi?", **corpo}, headers=auth_header(user_id)
    )


FINAL_OK = {
    "type": "final",
    "state": {"response": RESPOSTA, "selected_agents": ["consumption"], "chart_data": None},
}


def test_etapas_vem_antes_do_resultado_e_a_resposta_so_no_fim(client, monkeypatch):
    usa_eventos(monkeypatch, [
        {"type": "stage", "stage": "checking", "label": "Verificando a mensagem"},
        {"type": "stage", "stage": "querying", "label": "Consultando os dados"},
        FINAL_OK,
    ])

    resposta = post(client)

    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("text/event-stream")
    assert resposta.headers["cache-control"] == "no-cache"
    assert resposta.headers["x-accel-buffering"] == "no"
    eventos = eventos_sse(resposta.text)
    assert [nome for nome, _ in eventos] == ["stage", "stage", "result"]
    assert eventos[0][1] == {"stage": "checking", "label": "Verificando a mensagem"}
    assert RESPOSTA not in resposta.text.split("event: result")[0]
    resultado = eventos[-1][1]
    assert resultado["response"] == RESPOSTA
    assert resultado["agents_used"] == ["consumption"]
    assert resultado["chart_data"] is None
    assert memory.session_belongs_to_user(7, resultado["session_id"])


def test_sessao_existente_do_usuario_e_continuada(client, monkeypatch):
    sessao = memory.create_session(7)
    chamadas = usa_eventos(monkeypatch, [FINAL_OK])

    resposta = post(client, session_id=sessao)

    assert eventos_sse(resposta.text)[-1][1]["session_id"] == sessao
    assert chamadas == [(7, sessao, "Quanto consumi?")]


def test_sem_token_e_recusado(client):
    assert client.post("/chat/stream", json={"message": "oi"}).status_code == 401


def test_sessao_de_outro_usuario_da_404_antes_de_abrir_o_fluxo(client, monkeypatch):
    alheia = memory.create_session(8)
    chamadas = usa_eventos(monkeypatch, [FINAL_OK])

    resposta = post(client, user_id=7, session_id=alheia)

    assert resposta.status_code == 404
    assert resposta.headers["content-type"].startswith("application/json")
    assert chamadas == []


def test_sessao_inexistente_da_404_igual(client, monkeypatch):
    chamadas = usa_eventos(monkeypatch, [FINAL_OK])

    resposta = post(client, session_id="64b7f0f0f0f0f0f0f0f0f0f0")

    assert resposta.status_code == 404 and chamadas == []


def test_historico_indisponivel_da_503_antes_do_fluxo(client, monkeypatch):
    def cai(user_id):
        raise RuntimeError("mongo fora")

    monkeypatch.setattr(chat_route, "create_session", cai)
    chamadas = usa_eventos(monkeypatch, [FINAL_OK])

    resposta = post(client)

    assert resposta.status_code == 503 and chamadas == []


def test_mensagem_bloqueada_vira_evento_de_erro_422_e_remove_a_sessao_nova(client, monkeypatch):
    usa_eventos(monkeypatch, [
        {"type": "stage", "stage": "checking", "label": "Verificando a mensagem"},
        {"type": "final", "state": {"_blocked": True, "response": "Mensagem bloqueada."}},
    ])

    resposta = post(client)

    assert resposta.status_code == 200
    eventos = eventos_sse(resposta.text)
    assert eventos[-1] == ("error", {"status": 422, "detail": "Mensagem bloqueada."})
    assert "result" not in [nome for nome, _ in eventos]
    assert memory._collection().count_documents({"user_id": 7}) == 0


def test_bloqueio_em_sessao_existente_nao_apaga_a_sessao(client, monkeypatch):
    sessao = memory.create_session(7)
    usa_eventos(monkeypatch, [{"type": "final", "state": {"_blocked": True, "response": "Não."}}])

    post(client, session_id=sessao)

    assert memory.session_belongs_to_user(7, sessao)


def test_falha_do_fluxo_vira_erro_500_sem_detalhes_internos(client, monkeypatch):
    usa_eventos(monkeypatch, [
        {"type": "stage", "stage": "checking", "label": "Verificando a mensagem"},
        {"type": "failed"},
    ])

    resposta = post(client)

    eventos = eventos_sse(resposta.text)
    nome, dados = eventos[-1]
    assert nome == "error" and dados["status"] == 500
    assert dados["detail"] == "Não foi possível concluir a requisição."
    assert memory._collection().count_documents({"user_id": 7}) == 0


def test_fluxo_sem_resposta_e_tratado_como_falha(client, monkeypatch):
    usa_eventos(monkeypatch, [{"type": "final", "state": {}}])

    eventos = eventos_sse(post(client).text)

    assert eventos[-1][0] == "error" and eventos[-1][1]["status"] == 500


def test_keepalive_vira_comentario_sse(client, monkeypatch):
    usa_eventos(monkeypatch, [{"type": "keepalive"}, FINAL_OK])

    eventos = eventos_sse(post(client).text)

    assert [nome for nome, _ in eventos] == ["comment", "result"]


# --- run_workflow_events com um grafo falso ----------------------------------------------------


class GrafoFalso:
    def __init__(self, chunks=None, erro=None, atraso=0.0):
        self.chunks = chunks or []
        self.erro = erro
        self.atraso = atraso
        self.apagados = []
        self.checkpointer = SimpleNamespace(delete_thread=self.apagados.append)

    def get_state(self, config):
        return SimpleNamespace(values={"messages": ["já existe"]})

    def stream(self, initial, config=None, stream_mode=None):
        self.stream_mode = stream_mode
        for chunk in self.chunks:
            time.sleep(self.atraso)
            yield chunk
        if self.erro:
            raise self.erro


def roda(monkeypatch, grafo, **kwargs):
    monkeypatch.setattr(workflow, "workflow", grafo)
    return list(workflow.run_workflow_events(7, "s1", "oi", **kwargs))


CHUNKS = [
    ("updates", {"guardrail_input": {"question": "oi"}}),
    ("values", {"response": ""}),
    ("updates", {"prepare": {"intent": "x"}}),
    ("updates", {"execute": {"agent_results": []}}),
    ("updates", {"synthesize": {}}),
    ("updates", {"respond": {"response": RESPOSTA}}),
    ("updates", {"compose": {}}),
    ("updates", {"judge": {}}),
    ("updates", {"publish": {}}),
    ("updates", {"output_guard": {"response": RESPOSTA}}),
    ("values", {"response": RESPOSTA, "selected_agents": ["consumption"]}),
]


def test_eventos_de_etapa_sem_repeticao_e_estado_final(monkeypatch):
    grafo = GrafoFalso(CHUNKS)

    itens = roda(monkeypatch, grafo)

    etapas = [item["stage"] for item in itens if item["type"] == "stage"]
    assert etapas == ["checking", "understanding", "querying", "composing", "validating", "finishing"]
    assert itens[-1] == {"type": "final", "state": {"response": RESPOSTA, "selected_agents": ["consumption"]}}
    assert grafo.stream_mode == ["updates", "values"]


def test_etapas_nao_carregam_dados_da_conta_nem_da_resposta(monkeypatch):
    itens = roda(monkeypatch, GrafoFalso(CHUNKS))

    for item in itens:
        if item["type"] == "stage":
            assert set(item) == {"type", "stage", "label"}
            assert RESPOSTA not in item["label"]


def test_chat_apaga_o_checkpoint_ao_terminar_e_o_console_nao(monkeypatch):
    grafo = GrafoFalso(CHUNKS)
    roda(monkeypatch, grafo)
    assert grafo.apagados == ["7:s1"]

    outro = GrafoFalso(CHUNKS)
    roda(monkeypatch, outro, persist_session=False)
    assert outro.apagados == []


def test_erro_no_grafo_vira_failed_e_o_checkpoint_e_apagado(monkeypatch):
    grafo = GrafoFalso(CHUNKS[:2], erro=RuntimeError("falha no nó"))

    itens = roda(monkeypatch, grafo)

    assert itens[-1] == {"type": "failed"}
    assert not any(item["type"] == "final" for item in itens)
    assert grafo.apagados == ["7:s1"]


def test_keepalive_quando_o_grafo_demora(monkeypatch):
    grafo = GrafoFalso(CHUNKS[:1] + CHUNKS[-1:], atraso=0.25)

    itens = roda(monkeypatch, grafo, keepalive_seconds=0.05)

    assert any(item["type"] == "keepalive" for item in itens)
    assert itens[-1]["type"] == "final"


def test_o_grafo_roda_no_contexto_de_rastreamento_da_requisicao(monkeypatch):
    from app.observability.diagnostics import Trace, capture, current_trace

    vistos = []

    class Espia(GrafoFalso):
        def stream(self, initial, config=None, stream_mode=None):
            vistos.append(current_trace())
            yield from super().stream(initial, config, stream_mode)

    trace = Trace("chat", user_id=7)
    with capture(trace):
        roda(monkeypatch, Espia(CHUNKS))

    assert vistos == [trace]
