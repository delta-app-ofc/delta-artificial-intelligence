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

    def _resolve_scope(property_name: str | None):
        """Resolve o escopo (propriedade(s)) do user_id para esta chamada.

        Retorna (kind, property_ids, candidates):
        - ("residential", None, None): caminho antigo, via tb_user_property.
        - ("organizational", [ids...], [OrganizationProperty escolhidas]):
          sem property_name agrega todas as unidades da organização; com
          property_name batendo uma única unidade, filtra só nela.
        - ("organizational_ambiguous", None, [candidatas que bateram]):
          property_name bateu mais de uma unidade.
        - ("organizational_not_found", None, [todas as unidades]):
          property_name não bateu nenhuma unidade.
        - ("none", None, None): usuário sem residência nem organização.
        """
        kind = db_postgres.get_user_access_kind(user_id)
        if kind != "organizational":
            return kind, None, None

        all_props = db_postgres.get_user_organization_properties(user_id)
        needle = (property_name or "").strip().lower()
        if not needle:
            return "organizational", [p.property_id for p in all_props], all_props

        matches = [p for p in all_props if needle in p.name.lower()]
        if not matches:
            return "organizational_not_found", None, all_props
        if len(matches) > 1:
            return "organizational_ambiguous", None, matches
        return "organizational", [matches[0].property_id], matches

    def _scope_error_response(kind: str, candidates: list[Any] | None) -> dict:
        if kind == "none":
            return {
                "status": "insufficient_data",
                "message": "Usuário sem propriedade residencial ou organização vinculada.",
            }
        if kind == "organizational_not_found":
            return {
                "status": "insufficient_data",
                "message": "Nenhuma unidade da organização corresponde a esse nome.",
                "available_units": [_serialize(c) for c in candidates],
            }
        # "organizational_ambiguous"
        return {
            "status": "ambiguous",
            "message": "Mais de uma unidade corresponde a esse nome. Pergunte ao usuário qual ele quer dizer antes de prosseguir.",
            "candidates": [_serialize(c) for c in candidates],
        }

    @tool
    def check_can_estimate(property_name: str | None = None) -> dict:
        """Verifica se o usuário está apto a receber estimativas de previsão.

        Reproduz fn_user_can_estimate para usuário residencial: usuário ativo,
        propriedade vinculada, dispositivo ativo e tarifa cadastrada para a
        região. Para usuário de organização, verifica se há telemetria real
        registrada para alguma unidade. Chame esta tool antes de qualquer
        estimativa. Se can_estimate for false, informe que não há dados
        suficientes e não apresente números.

        Use property_name somente se o usuário mencionar uma unidade
        específica da organização pelo nome ou endereço (ex.: 'a filial da
        Rua X', 'unidade Centro'). Deixe em branco (padrão) quando a pergunta
        for sobre a organização como um todo — nesse caso os dados de todas
        as unidades são somados. Este parâmetro não tem efeito para usuários
        com propriedade residencial própria.
        """
        kind, ids, candidates = _resolve_scope(property_name)
        if kind == "residential":
            return {"status": "ok", "can_estimate": db_postgres.user_can_estimate(user_id)}
        if kind == "organizational":
            return {"status": "ok", "can_estimate": db_postgres.organization_can_estimate(ids)}
        return _scope_error_response(kind, candidates)

    @tool
    def get_last_bill(property_name: str | None = None) -> dict:
        """Última conta de água registrada do usuário (tb_last_water_bill),
        ou o equivalente organizacional (último período faturado nas unidades
        da organização, calculado a partir da telemetria real).

        Use como base da estimativa quando ainda não há histórico de consumo
        suficiente (primeiro uso).

        Use property_name somente se o usuário mencionar uma unidade
        específica da organização pelo nome ou endereço (ex.: 'a filial da
        Rua X', 'unidade Centro'). Deixe em branco (padrão) quando a pergunta
        for sobre a organização como um todo — nesse caso os dados de todas
        as unidades são somados. Este parâmetro não tem efeito para usuários
        com propriedade residencial própria.
        """
        kind, ids, candidates = _resolve_scope(property_name)
        if kind == "residential":
            bill = db_postgres.get_last_water_bill(user_id)
        elif kind == "organizational":
            bill = db_postgres.get_organization_last_billed_period(ids, today)
        else:
            return _scope_error_response(kind, candidates)
        if bill is None:
            return {"status": "insufficient_data", "message": "Sem conta anterior registrada."}
        return {"status": "ok", "last_bill": _serialize(bill)}

    @tool
    def get_consumption_history(days: int = DEFAULT_HISTORY_DAYS, property_name: str | None = None) -> dict:
        """Histórico de janelas de consumo (litros) dos últimos days dias.
        Para usuário residencial, vem do MongoDB; para usuário de organização,
        vem da telemetria real consolidada por dia nas unidades da
        organização. Lista vazia significa que não há histórico (não invente
        um).

        Use property_name somente se o usuário mencionar uma unidade
        específica da organização pelo nome ou endereço (ex.: 'a filial da
        Rua X', 'unidade Centro'). Deixe em branco (padrão) quando a pergunta
        for sobre a organização como um todo — nesse caso os dados de todas
        as unidades são somados. Este parâmetro não tem efeito para usuários
        com propriedade residencial própria.
        """
        kind, ids, candidates = _resolve_scope(property_name)
        if kind == "residential":
            points = db_mongo.get_consumption_history(user_id, days)
        elif kind == "organizational":
            points = db_postgres.get_organization_consumption_history(ids, days, today)
        else:
            return _scope_error_response(kind, candidates)
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
    def get_region_rate(property_name: str | None = None) -> dict:
        """Tarifa vigente (R$/m³) da região da propriedade do usuário, hoje.

        Para usuário residencial, usa fn_get_current_region_rate via SQL. Para
        usuário de organização, usa a tarifa efetiva observada nos últimos 30
        dias de telemetria real (as unidades de uma organização podem estar
        em regiões diferentes, então não há uma única tarifa "vigente" nesse
        caso). Necessária para estimativas monetárias baseadas em projeção de
        consumo.

        Use property_name somente se o usuário mencionar uma unidade
        específica da organização pelo nome ou endereço (ex.: 'a filial da
        Rua X', 'unidade Centro'). Deixe em branco (padrão) quando a pergunta
        for sobre a organização como um todo — nesse caso os dados de todas
        as unidades são somados. Este parâmetro não tem efeito para usuários
        com propriedade residencial própria.
        """
        kind, ids, candidates = _resolve_scope(property_name)
        if kind == "organizational":
            rate = db_postgres.get_organization_effective_rate(ids, today)
            if rate is None:
                return {
                    "status": "insufficient_data",
                    "message": "Sem consumo recente registrado para calcular uma tarifa efetiva.",
                }
            return {
                "status": "ok",
                "rate_m3": float(rate),
                "basis": "gold_effective_rate",
                "properties_considered": ids,
            }
        if kind != "residential":
            return _scope_error_response(kind, candidates)

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
    def calculate_forecast(history_days: int = DEFAULT_HISTORY_DAYS, property_name: str | None = None) -> dict:
        """Calcula a previsão completa de forma determinística (sem LLM).

        Junta elegibilidade, histórico, meta, tarifa e a última conta (ou o
        equivalente organizacional de cada uma dessas), e devolve: projeção de
        consumo até o fim do mês, estimativa da próxima conta (última conta se
        não houver histórico; projeção x tarifa se houver), tendência
        (alta/queda/estável) e risco de ultrapassar a meta.

        Se o usuário não estiver apto, retorna status "insufficient_data" e
        NENHUM cálculo é feito.

        Use property_name somente se o usuário mencionar uma unidade
        específica da organização pelo nome ou endereço (ex.: 'a filial da
        Rua X', 'unidade Centro'). Deixe em branco (padrão) quando a pergunta
        for sobre a organização como um todo — nesse caso os dados de todas
        as unidades são somados. Este parâmetro não tem efeito para usuários
        com propriedade residencial própria.
        """
        kind, ids, candidates = _resolve_scope(property_name)
        if kind not in ("residential", "organizational"):
            return _scope_error_response(kind, candidates)

        can_estimate = (
            db_postgres.user_can_estimate(user_id)
            if kind == "residential"
            else db_postgres.organization_can_estimate(ids)
        )
        if not can_estimate:
            return {
                "status": "insufficient_data",
                "message": (
                    "Sem cadastro suficiente para estimativas. Nenhum cálculo foi executado."
                ),
            }

        daily_target = db_mongo.get_daily_liters_target(user_id)

        if kind == "residential":
            history = db_mongo.get_consumption_history(user_id, history_days)
            last_bill = db_postgres.get_last_water_bill(user_id)
            region_id = db_postgres.get_user_region_id(user_id)
            classification_id = db_postgres.get_user_property_classification_id(user_id)
            region_rate: Decimal | None = None
            if region_id is not None and classification_id is not None:
                try:
                    region_rate = db_postgres.get_current_region_rate(region_id, classification_id, today)
                except RegionRateNotFound:
                    region_rate = None
        else:
            history = db_postgres.get_organization_consumption_history(ids, history_days, today)
            last_bill = db_postgres.get_organization_last_billed_period(ids, today)
            region_rate = db_postgres.get_organization_effective_rate(ids, today)

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
