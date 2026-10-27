"""Título, prévia e ícone gerados pela LLM (modelo substituído, sem chamada real)."""

from types import SimpleNamespace

import pytest

from app.memory import session as memory
from app.services import session_meta


class FakeModel:
    def __init__(self, content=None, error=None):
        self.content = content
        self.error = error
        self.prompts = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return SimpleNamespace(content=self.content)


@pytest.fixture
def use_model():
    def install(model):
        session_meta.llms.llm_rapido = model
        return model

    yield install
    session_meta.llms.__dict__.pop("llm_rapido", None)


def test_parse_accepts_json_inside_code_fence():
    raw = '```json\n{"title": "Hábitos a melhorar", "preview": "Se você diminuir 3min", "icon": "habits"}\n```'
    assert session_meta._parse_meta(raw) == {
        "title": "Hábitos a melhorar",
        "preview": "Se você diminuir 3min",
        "icon": "habits",
    }


def test_parse_replaces_unknown_icon_and_truncates():
    raw = '{"title": "%s", "preview": "%s", "icon": "foguete"}' % ("t" * 80, "p" * 200)

    meta = session_meta._parse_meta(raw)

    assert meta["icon"] == "general"
    assert len(meta["title"]) == 40 and len(meta["preview"]) == 80


@pytest.mark.parametrize(
    "raw",
    ["", "sem json", "{quebrado", "[1, 2]", '{"title": "", "preview": "x", "icon": "tips"}', '{"title": "x"}'],
)
def test_parse_rejects_unusable_output(raw):
    assert session_meta._parse_meta(raw) is None


def test_generate_sends_question_and_answer_with_icon_list(use_model):
    model = use_model(FakeModel('{"title": "Resumo do mês", "preview": "Você gastou 30% menos", "icon": "summary"}'))

    meta = session_meta.generate_session_meta("Resuma meu mês", "Você gastou 30% menos.")

    assert meta["icon"] == "summary"
    assert "Resuma meu mês" in model.prompts[0] and "Você gastou 30% menos." in model.prompts[0]
    assert all(icon in model.prompts[0] for icon in session_meta.ICONS)


def test_generate_without_model_returns_none(use_model):
    use_model(None)
    assert session_meta.generate_session_meta("a", "b") is None


def test_refresh_stores_meta_once_with_real_mongo(mongo_db, use_model):
    model = use_model(FakeModel('{"title": "Definir rotina nova", "preview": "Rotina para diminuir 12%", "icon": "routine"}'))
    session_id = memory.create_session(7)
    memory.append_turn(session_id, 7, "human", "Crie uma rotina")
    memory.append_turn(session_id, 7, "assistant", "Aqui está")

    session_meta.refresh_session_meta(7, session_id, "Crie uma rotina", "Aqui está")
    session_meta.refresh_session_meta(7, session_id, "outra pergunta", "outra resposta")

    item = memory.get_sessions_for_user(7)[0]
    assert (item["title"], item["icon"]) == ("Definir rotina nova", "routine")
    assert len(model.prompts) == 1  # a LLM só é chamada enquanto não há título


def test_refresh_never_raises_and_keeps_fallback(mongo_db, use_model):
    use_model(FakeModel(error=RuntimeError("provedor fora do ar")))
    session_id = memory.create_session(7)
    memory.append_turn(session_id, 7, "human", "Como economizar?")
    memory.append_turn(session_id, 7, "assistant", "Feche a torneira.")

    session_meta.refresh_session_meta(7, session_id, "Como economizar?", "Feche a torneira.")

    item = memory.get_sessions_for_user(7)[0]
    assert item["title"] == "Como economizar?" and item["icon"] == "general"
    assert memory.session_needs_meta(7, session_id) is True  # tentará de novo no próximo turno


def test_refresh_ignores_other_users_session(mongo_db, use_model):
    model = use_model(FakeModel('{"title": "T", "preview": "P", "icon": "tips"}'))
    session_id = memory.create_session(7)

    session_meta.refresh_session_meta(8, session_id, "q", "a")

    assert model.prompts == []
    assert memory.session_needs_meta(7, session_id) is True
