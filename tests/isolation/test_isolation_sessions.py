"""Sessões de chat: um usuário nunca lê, escreve ou fecha a sessão de outro (MongoDB real)."""

import pytest
from bson import ObjectId

from app.memory import session as memory
from tests.isolation.helpers import auth_header


def _chat(api, user_id, message="Como diminuir meu gasto?", session_id=None):
    body = {"message": message}
    if session_id:
        body["session_id"] = session_id
    return api.post("/chat", json=body, headers=auth_header(user_id))


# --- memória de sessão (sem HTTP) ---------------------------------------------------


def test_create_session_gera_id_no_servidor_e_grava_o_dono(mongo_db):
    session_id = memory.create_session(7)

    assert ObjectId.is_valid(session_id)
    doc = mongo_db.chat_sessions.find_one({"_id": ObjectId(session_id)})
    assert doc["user_id"] == 7 and doc["messages"] == []


def test_so_o_dono_le_o_historico(mongo_db):
    session_id = memory.create_session(7)
    memory.append_turn(session_id, 7, "human", "pergunta")

    assert len(memory.load_history_validated(7, session_id)) == 1
    assert memory.load_history_validated(8, session_id) == []
    assert memory.session_belongs_to_user(7, session_id) is True
    assert memory.session_belongs_to_user(8, session_id) is False


def test_append_turn_recusa_sessao_de_outro_usuario_sem_alterar(mongo_db):
    session_id = memory.create_session(7)

    with pytest.raises(ValueError):
        memory.append_turn(session_id, 8, "human", "intruso")

    assert mongo_db.chat_sessions.find_one({"_id": ObjectId(session_id)})["messages"] == []
    assert mongo_db.chat_sessions.count_documents({"_id": ObjectId(session_id)}) == 1


def test_listagem_so_traz_sessoes_do_usuario_e_com_mensagens(mongo_db):
    vazia = memory.create_session(7)
    minha = memory.create_session(7)
    memory.append_turn(minha, 7, "human", "oi")
    alheia = memory.create_session(8)
    memory.append_turn(alheia, 8, "human", "oi")

    ids = [item["session_id"] for item in memory.get_sessions_for_user(7)]

    assert ids == [minha]
    assert vazia not in ids and alheia not in ids


def test_sessao_excluida_some_para_o_dono_e_nao_aceita_escritas(mongo_db):
    session_id = memory.create_session(7)
    memory.append_turn(session_id, 7, "human", "oi")
    mongo_db.chat_sessions.update_one({"_id": ObjectId(session_id)}, {"$set": {"is_deleted": True}})

    assert memory.session_belongs_to_user(7, session_id) is False
    assert memory.load_history_validated(7, session_id) == []
    assert memory.get_sessions_for_user(7) == []
    with pytest.raises(ValueError):
        memory.append_turn(session_id, 7, "human", "volta")


def test_discard_empty_session_nao_apaga_sessao_com_mensagem_nem_de_outro(mongo_db):
    com_mensagem = memory.create_session(7)
    memory.append_turn(com_mensagem, 7, "human", "oi")
    vazia = memory.create_session(7)

    memory.discard_empty_session(7, com_mensagem)
    memory.discard_empty_session(8, vazia)  # outro usuário não apaga
    assert memory.session_belongs_to_user(7, com_mensagem) is True
    assert memory.session_belongs_to_user(7, vazia) is True

    memory.discard_empty_session(7, vazia)
    assert memory.session_belongs_to_user(7, vazia) is False


# --- rotas -----------------------------------------------------------------------------


def test_chat_cria_sessao_no_servidor_e_continua_a_propria(api, mongo_db):
    first = _chat(api, 7)
    assert first.status_code == 200
    session_id = first.json()["session_id"]
    assert mongo_db.chat_sessions.count_documents({"_id": ObjectId(session_id), "user_id": 7}) == 1

    second = _chat(api, 7, "e a rotina?", session_id=session_id)

    assert second.json()["session_id"] == session_id
    assert len(mongo_db.chat_sessions.find_one({"_id": ObjectId(session_id)})["messages"]) == 4


def test_chat_recusa_session_id_escolhido_pelo_cliente(api, mongo_db):
    response = _chat(api, 7, session_id="minha-sessao-inventada")

    assert response.status_code == 404
    assert mongo_db.chat_sessions.count_documents({}) == 0


def test_chat_com_sessao_alheia_e_inexistente_respondem_igual(api, mongo_db):
    alheia = _chat(api, 7).json()["session_id"]

    intruso = _chat(api, 8, "intruso", session_id=alheia)
    inexistente = _chat(api, 8, "oi", session_id=str(ObjectId()))

    assert intruso.status_code == inexistente.status_code == 404
    assert intruso.json() == inexistente.json()
    assert len(mongo_db.chat_sessions.find_one({"_id": ObjectId(alheia)})["messages"]) == 2


def test_mensagens_so_para_o_dono_e_sem_revelar_existencia(api):
    session_id = _chat(api, 7, "oi").json()["session_id"]

    proprio = api.get(f"/sessions/{session_id}/messages", headers=auth_header(7))
    alheio = api.get(f"/sessions/{session_id}/messages", headers=auth_header(8))
    inexistente = api.get(f"/sessions/{ObjectId()}/messages", headers=auth_header(8))

    assert proprio.status_code == 200 and len(proprio.json()["messages"]) == 2
    assert alheio.status_code == inexistente.status_code == 404
    assert alheio.json() == inexistente.json()


def test_listagem_da_rota_so_traz_as_sessoes_do_token(api):
    minha = _chat(api, 7).json()["session_id"]
    _chat(api, 8)

    ids = [s["session_id"] for s in api.get("/sessions", headers=auth_header(7)).json()["sessions"]]

    assert ids == [minha]


def test_user_id_enviado_pelo_cliente_e_ignorado(api):
    _chat(api, 7)

    como_sete = api.get("/sessions?user_id=7", headers=auth_header(8))
    corpo = api.post("/chat", json={"message": "oi", "user_id": 7}, headers=auth_header(8))

    assert como_sete.json()["sessions"] == []
    sessao = corpo.json()["session_id"]
    assert memory.session_belongs_to_user(8, sessao) is True
    assert memory.session_belongs_to_user(7, sessao) is False


def test_fechar_sessao_de_outro_usuario_responde_404_e_nao_chama_o_resumo(api, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.routes.sessions.close_session", lambda session_id, user_id: calls.append((session_id, user_id))
    )
    session_id = _chat(api, 7).json()["session_id"]

    intruso = api.post(f"/sessions/{session_id}/close", headers=auth_header(8))
    dono = api.post(f"/sessions/{session_id}/close", headers=auth_header(7))

    assert intruso.status_code == 404
    assert dono.status_code == 200
    assert calls == [(session_id, 7)]


def test_pergunta_bloqueada_nao_deixa_sessao_vazia(api, mongo_db, monkeypatch):
    monkeypatch.setattr(
        "app.routes.chat.run_workflow",
        lambda user_id, session_id, question: {"_blocked": True, "response": "Mensagem não permitida."},
    )

    response = _chat(api, 7, "mensagem bloqueada")

    assert response.status_code == 422
    assert mongo_db.chat_sessions.count_documents({}) == 0


def test_sem_token_nenhuma_rota_de_dados_responde(api):
    assert api.post("/chat", json={"message": "oi"}).status_code == 401
    assert api.get("/sessions").status_code == 401
    assert api.get(f"/sessions/{ObjectId()}/messages").status_code == 401
    assert api.post(f"/sessions/{ObjectId()}/close").status_code == 401
