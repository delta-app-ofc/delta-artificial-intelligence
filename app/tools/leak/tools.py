"""As tools de verdade do Agente de Vazamento — o que o LLM efetivamente chama.

Só MongoDB, sem tool de cálculo/limiar próprio: o indício vem do que o motor
de detecção (repositório delta-business-rules) já sinalizou.
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime
from typing import Any

from langchain_core.tools import BaseTool, tool

from app.data import db_mongo
from app.tools.leak import analysis

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


def build_tools(user_id: int) -> list[BaseTool]:
    """Cria as tools já amarradas a user_id (não exposto ao LLM)."""

    @tool
    def get_anomalous_windows(days: int = DEFAULT_ANALYSIS_DAYS) -> dict:
        """Janelas de consumo dos últimos days dias já sinalizadas como
        anômalas (anomaly_detected true) por outro componente do sistema.

        Lista vazia = nenhum indício sinalizado no período. Não interprete
        ausência como garantia de que não há vazamento; interprete presença
        como indício, nunca como diagnóstico.
        """
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
        windows = db_mongo.get_anomalous_consumption_windows(user_id, days)
        summary = analysis.summarize_anomalous_windows(windows)
        return {
            "status": "ok" if summary.total_windows else "insufficient_data",
            "summary": _serialize(summary),
        }

    return [get_anomalous_windows, get_alerts_history, summarize_anomalous_windows]
