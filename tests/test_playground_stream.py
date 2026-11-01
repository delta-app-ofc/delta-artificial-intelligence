"""POST /playground/chat/stream: etapas ao vivo e o mesmo resultado do /playground/chat."""

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import playground

RESPOSTA = "Você consumiu 120 litros."


def eventos_sse(texto: str) -> list[tuple[str, dict]]:
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
def client(monkeypatch):
    monkeypatch.setattr(playground, "get_settings", lambda: SimpleNamespace(playground_enabled=True))
    monkeypatch.setattr(
        playground, "validate_input_rules", lambda user_id, message: {"ok": True, "message": message, "pii_map": {}}
    )
    monkeypatch.setattr(playground, "append_turn", lambda *args, **kwargs: None)
    app = FastAPI()
    app.include_router(playground.router)
    return TestClient(app)


def usa_eventos(monkeypatch, itens, erro=None):
    chamadas = []

    def falso(user_id, session_id, question, **kwargs):
        chamadas.append((user_id, session_id, question, kwargs))
        yield from itens
        if erro:
            raise erro

    monkeypatch.setattr(playground, "run_workflow_events", falso)
    return chamadas


ESTADO_FINAL = {
    "response": RESPOSTA, "selected_agents": ["consumption"], "chart_data": None,
    "agent_results": [{"agent": "consumption", "status": "success", "answer": RESPOSTA}],
    "judge_history": [], "warnings": [],
}
ETAPAS = [
    {"type": "stage", "stage": "checking", "label": "Verificando a mensagem"},
    {"type": "stage", "stage": "planning", "label": "Vou consultar o seu consumo"},
    {"type": "stage", "stage": "working", "label": "Lendo o consumo registrado"},
    {"type": "final", "state": ESTADO_FINAL},
]


def post(client, **corpo):
    return client.post("/playground/chat/stream", json={"message": "Quanto consumi?", **corpo})


def test_etapas_chegam_antes_do_resultado(client, monkeypatch):
    usa_eventos(monkeypatch, ETAPAS)

    resposta = post(client)

    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("text/event-stream")
    assert resposta.headers["cache-control"] == "no-cache"
    eventos = eventos_sse(resposta.text)
    assert [nome for nome, _ in eventos] == ["stage", "stage", "stage", "result"]
    assert eventos[1][1] == {"stage": "planning", "label": "Vou consultar o seu consumo"}
    assert RESPOSTA not in resposta.text.split("event: result")[0]


def test_resultado_tem_o_mesmo_formato_do_playground_chat(client, monkeypatch):
    usa_eventos(monkeypatch, ETAPAS)

    resultado = eventos_sse(post(client).text)[-1][1]

    assert resultado["status"] == "success"
    assert resultado["response"] == RESPOSTA
    assert resultado["session_id"]
    assert resultado["agent_results"][0]["agent"] == "consumption"
    assert "diagnostics" in resultado and "judge_results" in resultado
    assert resultado["diagnostics"]["mode"] == "chat"


def test_usa_o_usuario_fixo_e_nao_persiste_no_checkpoint(client, monkeypatch):
    chamadas = usa_eventos(monkeypatch, ETAPAS)

    post(client, session_id="minha-sessao")

    user_id, session_id, pergunta, kwargs = chamadas[0]
    assert (user_id, session_id, pergunta) == (playground.USER_ID, "minha-sessao", "Quanto consumi?")
    assert kwargs == {"persist_session": False}


def test_falha_do_fluxo_aparece_nos_diagnosticos_do_resultado(client, monkeypatch):
    usa_eventos(monkeypatch, [ETAPAS[0], {"type": "failed"}])

    eventos = eventos_sse(post(client).text)

    assert eventos[0][0] == "stage"
    nome, dados = eventos[-1]
    assert nome == "result"  # o console mostra a falha dentro dos diagnósticos, como o /playground/chat
    assert dados["status"] == "error"
    assert dados["diagnostics"]["errors"]


def test_excecao_inesperada_vira_erro_500(client, monkeypatch):
    monkeypatch.setattr(playground, "run_test", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("segredo interno")))

    resposta = post(client)

    nome, dados = eventos_sse(resposta.text)[-1]
    assert nome == "error" and dados["status"] == 500
    assert "segredo interno" not in resposta.text


def test_mensagem_bloqueada_pela_guarda_vira_resultado_com_erro(client, monkeypatch):
    monkeypatch.setattr(
        playground, "validate_input_rules",
        lambda user_id, message: {"ok": False, "reason": "Mensagem bloqueada."},
    )
    chamadas = usa_eventos(monkeypatch, ETAPAS)

    eventos = eventos_sse(post(client).text)

    assert [nome for nome, _ in eventos] == ["result"]
    assert eventos[0][1]["status"] == "error" and eventos[0][1]["response"] == ""
    assert chamadas == []  # o fluxo nem começou


def test_console_desativado_responde_404(client, monkeypatch):
    monkeypatch.setattr(playground, "get_settings", lambda: SimpleNamespace(playground_enabled=False))

    assert post(client).status_code == 404


def test_corpo_invalido_e_recusado(client):
    assert client.post("/playground/chat/stream", json={"message": ""}).status_code == 422
    assert client.post("/playground/chat/stream", json={"message": "oi", "extra": 1}).status_code == 422


def test_o_chat_normal_do_console_continua_igual(client, monkeypatch):
    estado = {**ESTADO_FINAL}
    monkeypatch.setattr(playground, "run_workflow", lambda *a, **k: estado)

    resposta = client.post("/playground/chat", json={"message": "Quanto consumi?"})

    assert resposta.status_code == 200
    assert resposta.json()["response"] == RESPOSTA


# --- o session_id não pode ser alterado pelo redator de dados pessoais ---------------------------
# Este UUID tem sequências que o redator confunde com telefone ou CPF.
UUID_QUE_PARECE_TELEFONE = "5b215538-6503-498d-9f1b-df0507204b55"
UUID_QUE_PARECE_CPF = "25d4a0ff-5a26-45a9-9bfd-606369071296"
PADRAO_DO_CONSOLE = r"^[A-Za-z0-9_-]{1,100}$"


@pytest.mark.parametrize("session_id", [UUID_QUE_PARECE_TELEFONE, UUID_QUE_PARECE_CPF])
def test_envelope_devolve_o_session_id_sem_redacao(session_id):
    from app.observability.diagnostics import Trace

    resultado = playground.envelope(Trace(mode="chat"), session_id)

    assert resultado["session_id"] == session_id


@pytest.mark.parametrize("session_id", [UUID_QUE_PARECE_TELEFONE, UUID_QUE_PARECE_CPF])
def test_session_id_devolvido_pode_ser_reenviado_pelo_console(client, monkeypatch, session_id):
    import re

    usa_eventos(monkeypatch, ETAPAS)
    monkeypatch.setattr(playground.uuid, "uuid4", lambda: session_id)

    primeiro = eventos_sse(post(client).text)[-1][1]["session_id"]

    assert re.fullmatch(PADRAO_DO_CONSOLE, primeiro)
    assert client.post("/playground/chat/stream", json={"message": "de novo", "session_id": primeiro}).status_code == 200


def test_chat_sem_stream_tambem_devolve_o_id_sem_redacao(client, monkeypatch):
    monkeypatch.setattr(playground, "run_workflow", lambda *a, **k: {**ESTADO_FINAL})
    monkeypatch.setattr(playground.uuid, "uuid4", lambda: UUID_QUE_PARECE_TELEFONE)

    resposta = client.post("/playground/chat", json={"message": "oi"})

    assert resposta.json()["session_id"] == UUID_QUE_PARECE_TELEFONE
