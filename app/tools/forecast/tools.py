"""As tools de verdade do Agente de Previsão — o que o LLM efetivamente chama.

Cada função abaixo vira uma tool via @tool. A docstring de cada uma é o que o
LLM lê pra saber quando e como chamar — por isso são bem explicadas aqui, e o
prompt do agente (app/services/prompts.py) só precisa citar o nome de cada
uma, sem repetir a descrição.
"""

from __future__ import annotations

import dataclasses
from datetime import date
from decimal import Decimal
from typing import Any

from langchain_core.tools import BaseTool, tool

from app.data import db_mongo, db_postgres
from app.tools.exceptions import RegionRateNotFound
from app.tools.forecast import calculations as calc

# Janela padrão de histórico consultada no MongoDB (dias).
DEFAULT_HISTORY_DAYS = 45


def _serialize(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {k: _serialize(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (list, tuple)):
        return [_serialize(v) for v in value]
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, date):
        return value.isoformat()
    return value


def build_tools(user_id: int, today: date) -> list[BaseTool]:
    """Cria as tools já amarradas a user_id e à data de referência.

    O user_id NUNCA é um argumento exposto ao LLM — ele não pode inventá-lo.
    """

    @tool
    def check_can_estimate() -> dict:
        """Verifica se o usuário está apto a receber estimativas de previsão.

        Reproduz fn_user_can_estimate: usuário ativo, propriedade vinculada,
        dispositivo ativo e tarifa cadastrada para a região. Chame esta tool
        antes de qualquer estimativa. Se can_estimate for false, informe que
        não há dados suficientes e não apresente números.
        """
        return {"status": "ok", "can_estimate": db_postgres.user_can_estimate(user_id)}

    @tool
    def get_last_bill() -> dict:
        """Última conta de água registrada do usuário (tb_last_water_bill).

        Use como base da estimativa quando ainda não há histórico de consumo
        suficiente (primeiro uso).
        """
        bill = db_postgres.get_last_water_bill(user_id)
        if bill is None:
            return {"status": "insufficient_data", "message": "Sem conta anterior registrada."}
        return {"status": "ok", "last_bill": _serialize(bill)}

    @tool
    def get_consumption_history(days: int = DEFAULT_HISTORY_DAYS) -> dict:
        """Histórico de janelas de consumo (litros) dos últimos days dias, do
        MongoDB. Lista vazia significa que não há histórico (não invente um).
        """
        points = db_mongo.get_consumption_history(user_id, days)
        return {
            "status": "ok" if points else "insufficient_data",
            "days": days,
            "total_windows": len(points),
            "windows": [_serialize(p) for p in points],
        }

    @tool
    def get_daily_target() -> dict:
        """Meta diária de consumo do usuário (user_preferences.daily_liters_target).

        Necessária para responder "vou ultrapassar minha meta?". None quando
        não há meta cadastrada — nesse caso não afirme nada sobre a meta.
        """
        target = db_mongo.get_daily_liters_target(user_id)
        if target is None:
            return {"status": "insufficient_data", "message": "Meta diária não cadastrada."}
        return {"status": "ok", "daily_liters_target": target}

    @tool
    def get_region_rate() -> dict:
        """Tarifa vigente (R$/m³) da região da propriedade do usuário, hoje.

        Usa fn_get_current_region_rate via SQL. Necessária para estimativas
        monetárias baseadas em projeção de consumo.
        """
        region_id = db_postgres.get_user_region_id(user_id)
        classification_id = db_postgres.get_user_property_classification_id(user_id)
        if region_id is None or classification_id is None:
            return {"status": "insufficient_data", "message": "Usuário sem região ou categoria de imóvel identificável."}
        try:
            rate = db_postgres.get_current_region_rate(region_id, classification_id, today)
        except RegionRateNotFound as exc:
            return {"status": "insufficient_data", "message": str(exc)}
        return {"status": "ok", "region_id": region_id, "classification_id": classification_id, "rate_m3": float(rate)}

    @tool
    def calculate_forecast(history_days: int = DEFAULT_HISTORY_DAYS) -> dict:
        """Calcula a previsão completa de forma determinística (sem LLM).

        Junta fn_user_can_estimate, histórico, meta, tarifa e a última conta,
        e devolve: projeção de consumo até o fim do mês, estimativa da próxima
        conta (última conta se não houver histórico; projeção x tarifa se
        houver), tendência (alta/queda/estável) e risco de ultrapassar a meta.

        Se o usuário não estiver apto (fn_user_can_estimate = false), retorna
        status "insufficient_data" e NENHUM cálculo é feito.
        """
        can_estimate = db_postgres.user_can_estimate(user_id)
        if not can_estimate:
            return {
                "status": "insufficient_data",
                "message": (
                    "fn_user_can_estimate retornou False: sem cadastro suficiente "
                    "para estimativas. Nenhum cálculo foi executado."
                ),
            }

        history = db_mongo.get_consumption_history(user_id, history_days)
        last_bill = db_postgres.get_last_water_bill(user_id)
        daily_target = db_mongo.get_daily_liters_target(user_id)

        region_id = db_postgres.get_user_region_id(user_id)
        classification_id = db_postgres.get_user_property_classification_id(user_id)
        region_rate: Decimal | None = None
        if region_id is not None and classification_id is not None:
            try:
                region_rate = db_postgres.get_current_region_rate(region_id, classification_id, today)
            except RegionRateNotFound:
                region_rate = None

        result = calc.calculate_full_forecast(
            can_estimate=can_estimate,
            history=history,
            last_bill=last_bill,
            region_rate=region_rate,
            daily_target=daily_target,
            today=today,
        )
        return {"status": "ok", "forecast": _serialize(result)}

    return [
        check_can_estimate,
        get_last_bill,
        get_consumption_history,
        get_daily_target,
        get_region_rate,
        calculate_forecast,
    ]
