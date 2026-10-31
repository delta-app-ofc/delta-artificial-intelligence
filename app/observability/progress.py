"""Progresso da pergunta para o endpoint de streaming: rótulos fixos, sem dado da conta nem da resposta.

Os textos são escritos por nós por agente e por tool. Nada vindo do modelo (parâmetros, nomes de unidade,
períodos) entra no rótulo, porque ele ainda não passou pela validação do Juiz.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Callable

ProgressSink = Callable[[str, str], None]

_sink: ContextVar[ProgressSink | None] = ContextVar("progress_sink", default=None)

# Rótulo ao começar cada agente; o do consumo muda conforme o perfil da conta.
_AGENT_LABELS = {
    "consumption": "Consultando o seu consumo",
    "forecast": "Calculando a previsão",
    "leak": "Verificando alertas de vazamento",
    "habits": "Consultando os seus hábitos",
    "rag": "Buscando na documentação do Delta",
}
_AGENT_LABELS_ORGANIZATIONAL = {
    "consumption": "Consultando o consumo das suas unidades",
    "forecast": "Calculando a previsão das suas unidades",
}

# Rótulo de cada tool (nome fixo no código). Tool fora desta lista não gera evento.
_TOOL_LABELS = {
    "list_consumption_units": "Listando as suas unidades",
    "get_consumption_summary": "Lendo o consumo registrado",
    "compare_consumption_periods": "Comparando períodos de consumo",
    "get_consumption_peaks": "Procurando os picos de consumo",
    "check_can_estimate": "Conferindo se há dados para a previsão",
    "get_last_bill": "Lendo a última conta",
    "get_consumption_history": "Lendo o histórico de consumo",
    "get_daily_target": "Lendo a meta diária",
    "get_region_rate": "Consultando a tarifa",
    "calculate_forecast": "Calculando a previsão",
    "get_anomalous_windows": "Lendo as janelas de consumo anômalas",
    "get_alerts_history": "Lendo os alertas registrados",
    "summarize_anomalous_windows": "Resumindo os sinais de vazamento",
    "list_habits": "Lendo os seus hábitos",
    "get_habits_by_day": "Lendo os hábitos do dia",
    "create_habit": "Cadastrando o hábito",
    "estimate_habit_water_impact": "Estimando o impacto do hábito",
    "get_weather_history": "Consultando o clima",
    "search_knowledge_base": "Buscando na documentação do Delta",
}

# O que "Vou consultar ..." diz de cada agente.
_PLAN_PHRASES = {
    "consumption": "o seu consumo",
    "forecast": "a previsão de consumo",
    "leak": "possíveis vazamentos",
    "habits": "os seus hábitos",
    "rag": "a documentação do Delta",
}
_PLAN_PHRASES_ORGANIZATIONAL = {
    "consumption": "o consumo das suas unidades",
    "forecast": "a previsão das suas unidades",
}


def set_progress_sink(sink: ProgressSink | None) -> Token:
    """Liga (ou desliga, com None) o destino do progresso na requisição atual."""
    return _sink.set(sink)


def reset_progress_sink(token: Token) -> None:
    _sink.reset(token)


def _report(stage: str, label: str) -> None:
    sink = _sink.get()
    if sink is None:
        return
    try:
        sink(stage, label)
    except Exception:
        # O progresso é só informativo: nunca pode derrubar a pergunta.
        pass


def report_agent_started(agent: str, access_kind: str | None = None) -> None:
    labels = _AGENT_LABELS_ORGANIZATIONAL if access_kind == "organizational" else {}
    label = labels.get(agent) or _AGENT_LABELS.get(agent)
    if label:
        _report("working", label)


def report_tool_started(tool_name: str) -> None:
    label = _TOOL_LABELS.get(tool_name)
    if label:
        _report("working", label)


def plan_label(agents: list[str], access_kind: str | None = None) -> str | None:
    """Frase do que vai ser consultado, montada só com os agentes escolhidos pelo roteador."""
    phrases_org = _PLAN_PHRASES_ORGANIZATIONAL if access_kind == "organizational" else {}
    phrases = [
        phrases_org.get(agent) or _PLAN_PHRASES[agent]
        for agent in dict.fromkeys(agents)
        if agent in _PLAN_PHRASES
    ]
    if not phrases:
        return None
    joined = phrases[0] if len(phrases) == 1 else ", ".join(phrases[:-1]) + " e " + phrases[-1]
    return f"Vou consultar {joined}"
