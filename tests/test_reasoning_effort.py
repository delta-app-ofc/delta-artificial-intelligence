"""Nível de raciocínio por papel: especialistas em high, chamadas rápidas em low; o Juiz segue o geral."""

import pytest

from app.config import ConfigurationError, load_settings, validate_llm_config
from app.services import llms

BASE = {"APP_ENV": "test", "LLM_PROVIDER": "openai", "OPENAI_API_KEY": "chave-de-teste"}


def settings(**extra):
    return load_settings({**BASE, **extra}, env_file=None)


@pytest.fixture
def espia(monkeypatch):
    """Registra com qual raciocínio cada papel pede o modelo OpenAI; nada chama a rede."""
    pedidos = []

    def falso(settings_arg=None, *, reasoning_effort=None):
        pedidos.append(reasoning_effort)
        return object()

    monkeypatch.setattr(llms, "_get_llm_openai", falso)
    llms.clear_llm_cache()
    yield pedidos
    llms.clear_llm_cache()


def usa(monkeypatch, config):
    monkeypatch.setattr(llms, "get_settings", lambda: config)
    monkeypatch.setattr(llms, "validate_llm_config", lambda **kwargs: None)


def test_padrao_dos_especialistas_e_high():
    assert settings().openai_specialist_reasoning_effort == "high"


def test_padrao_das_chamadas_rapidas_e_low_e_o_geral_continua_medium():
    config = settings()

    assert config.openai_fast_reasoning_effort == "low"
    assert config.openai_reasoning_effort == "medium"  # usado, por exemplo, pelo Juiz


def test_especialista_pede_high(espia, monkeypatch):
    usa(monkeypatch, settings())

    llms._get_llm_especialista()

    assert espia == ["high"]


def test_papel_rapido_pede_low(espia, monkeypatch):
    usa(monkeypatch, settings())

    llms._get_llm_rapido()

    assert espia == ["low"]


def test_papel_rapido_com_nivel_proprio(espia, monkeypatch):
    usa(monkeypatch, settings(OPENAI_FAST_REASONING_EFFORT="medium"))

    llms._get_llm_rapido()

    assert espia == ["medium"]


def test_variavel_vazia_do_papel_rapido_volta_ao_nivel_geral(espia, monkeypatch):
    usa(monkeypatch, settings(OPENAI_FAST_REASONING_EFFORT=""))

    llms._get_llm_rapido()

    assert espia == [None]


def test_nivel_do_especialista_configuravel(espia, monkeypatch):
    usa(monkeypatch, settings(OPENAI_SPECIALIST_REASONING_EFFORT="xhigh"))

    llms._get_llm_especialista()

    assert espia == ["xhigh"]


def test_variavel_vazia_do_especialista_volta_ao_nivel_geral(espia, monkeypatch):
    usa(monkeypatch, settings(OPENAI_SPECIALIST_REASONING_EFFORT=""))

    llms._get_llm_especialista()

    assert espia == [None]


def test_valor_invalido_e_recusado_na_validacao():
    config = settings(OPENAI_SPECIALIST_REASONING_EFFORT="altissimo")

    with pytest.raises(ConfigurationError) as erro:
        validate_llm_config(provider="specialist", settings=config)

    assert "OPENAI_SPECIALIST_REASONING_EFFORT" in str(erro.value)


def test_modelos_openai_sao_distintos_por_nivel(monkeypatch):
    """O cache guarda um cliente por (configuração, nível): especialista e guarda não compartilham o mesmo."""
    criados = []

    class ModeloFalso:
        def __init__(self, **kwargs):
            criados.append(kwargs["reasoning"]["effort"])

    monkeypatch.setattr(llms, "ChatOpenAI", ModeloFalso)
    monkeypatch.setattr(llms, "validate_llm_config", lambda **kwargs: None)
    config = settings()

    llms._get_llm_openai(config, reasoning_effort="high")
    llms._get_llm_openai(config)
    llms._get_llm_openai(config, reasoning_effort="high")  # reaproveitado

    assert criados == ["high", "medium"]


def test_effort_appears_in_the_model_row_of_the_trace():
    from app.observability.diagnostics import ModelDiagnostics, Trace, capture

    trace = Trace(mode="chat")
    with capture(trace):
        handler = ModelDiagnostics("openai", "gpt-6-luna", "high")
        handler.on_chat_model_start({}, [[]], run_id="r1")
        handler._finish("r1", "success")
    row = trace.models[-1]
    assert row["model"] == "gpt-6-luna" and row["reasoning_effort"] == "high"
    ended = [e for e in trace.events if e["event"] == "model.end"][-1]
    assert ended["metadata"]["reasoning_effort"] == "high"


def test_model_row_without_effort_stays_as_before():
    from app.observability.diagnostics import ModelDiagnostics, Trace, capture

    trace = Trace(mode="chat")
    with capture(trace):
        ModelDiagnostics("groq", "llama").on_chat_model_start({}, [[]], run_id="r2")
    assert "reasoning_effort" not in trace.models[-1]
