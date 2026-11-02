"""As tools de verdade do Agente de Vazamento — o que o LLM efetivamente chama.

Só MongoDB, sem tool de cálculo/limiar próprio: o indício vem do que o motor
de detecção (repositório delta-business-rules) já sinalizou.
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime
from typing import Any

from langchain_core.tools import BaseTool, tool

from app.data import db_mongo, db_postgres
from app.tools.habits.tools import normalize_day
from app.tools.leak import analysis
from app.tools.validation import days_error, validate_user_id

# Janela padrão de análise (dias).
DEFAULT_ANALYSIS_DAYS = 30


def _serialize(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {k: _serialize(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(v) for v in value]
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def build_tools(user_id: int, access_kind: str | None = None) -> list[BaseTool]:
    """Cria as tools já amarradas a user_id (não exposto ao LLM)."""
    validate_user_id(user_id)

    @tool
    def get_anomalous_windows(days: int = DEFAULT_ANALYSIS_DAYS) -> dict:
        """Janelas de consumo dos últimos days dias já sinalizadas como
        anômalas (anomaly_detected true) por outro componente do sistema.

        Lista vazia = nenhum indício sinalizado no período. Não interprete
        ausência como garantia de que não há vazamento; interprete presença
        como indício, nunca como diagnóstico.
        """
        if invalid := days_error(days):
            return invalid
        windows = db_mongo.get_anomalous_consumption_windows(user_id, days)
        return {
            "status": "ok" if windows else "insufficient_data",
            "days": days,
            "total_anomalous_windows": len(windows),
            "windows": [_serialize(w) for w in windows],
        }

    @tool
    def get_alerts_history(days: int = DEFAULT_ANALYSIS_DAYS, only_active: bool = False) -> dict:
        """Alertas já disparados para o usuário em alerts_history nos últimos
        days dias (vazamento_continuo, fluxo_atipico etc.).

        Com only_active=True retorna só os não resolvidos (resolved_at nulo).
        """
        if invalid := days_error(days):
            return invalid
        alerts = db_mongo.get_alerts_history(user_id, days, only_active=only_active)
        return {
            "status": "ok" if alerts else "insufficient_data",
            "days": days,
            "only_active": only_active,
            "total_alerts": len(alerts),
            "alerts": [_serialize(a) for a in alerts],
        }

    @tool
    def summarize_anomalous_windows(days: int = DEFAULT_ANALYSIS_DAYS) -> dict:
        """Resumo descritivo das janelas anômalas do período (quantas, quando
        começaram/terminaram, duração total, litros, quantas de madrugada).

        Serve só para você explicar o padrão já sinalizado em linguagem
        natural. Não cria nenhum critério novo de detecção.
        """
        if invalid := days_error(days):
            return invalid
        windows = db_mongo.get_anomalous_consumption_windows(user_id, days)
        summary = analysis.summarize_anomalous_windows(windows)
        return {
            "status": "ok" if summary.total_windows else "insufficient_data",
            "summary": _serialize(summary),
        }

    @tool
    def get_habit_windows(day: str | None = None) -> dict:
        """Hábitos cadastrados do usuário (dias e horários) para comparar com uma janela anômala.

        day: dia da semana em português (seg, terça, sábado...); em branco, todos os dias.

        Um hábito que coincide com o dia e o horário de uma janela é uma explicação
        possível, mas NUNCA descarta o indício nem confirma ou afasta vazamento. Hábito
        sem horário só permite comparar pelo dia. Sem hábitos, não diga nada sobre eles.
        Disponível só para conta residencial.
        """
        kind = access_kind or db_postgres.get_user_access_kind(user_id)
        if kind != "residential":
            return {"status": "not_applicable", "message": "Hábitos só existem em contas residenciais."}
        if day:
            canonical = normalize_day(day)
            if canonical is None:
                return {"status": "error", "message": f"Dia '{day}' não reconhecido."}
            habits = db_postgres.get_habits_by_weekday(user_id, canonical)
        else:
            habits = db_postgres.get_user_habits(user_id)
        if not habits:
            return {"status": "insufficient_data", "message": "Nenhum hábito cadastrado para esse recorte."}
        return {
            "status": "ok",
            "habits": [
                {**h, "has_schedule": bool(h.get("start_time") and h.get("end_time"))} for h in habits
            ],
            "note": "Hábito é só contexto: não prova nem afasta vazamento.",
        }

    return [get_anomalous_windows, get_alerts_history, summarize_anomalous_windows, get_habit_windows]
