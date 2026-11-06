"""As tools de verdade do Agente de Previsão — o que o LLM efetivamente chama.

Cada função abaixo vira uma tool via @tool. A docstring de cada uma é o que o
LLM lê pra saber quando e como chamar — por isso são bem explicadas aqui, e o
prompt do agente (app/services/prompts.py) só precisa citar o nome de cada
uma, sem repetir a descrição.
"""

from __future__ import annotations

import calendar
import dataclasses
import logging
import math
import re
from datetime import date
from decimal import Decimal
from typing import Any

from langchain_core.tools import BaseTool, tool

from app.config import ConfigurationError, get_settings
from app.data import db_mongo, db_postgres
from app.tools.exceptions import (
    DatabaseAccessError,
    DatabaseDataError,
    LastWaterBillConflictError,
    RegionRateNotFound,
)
from app.tools.forecast import calculations as calc
from app.tools.habits.calculations import summarize_habit_baseline
from app.tools.simulation.calculations import simulate_percentage_change
from app.tools.validation import days_error, validate_user_id

logger = logging.getLogger(__name__)

# Janela padrão de histórico consultada no MongoDB (dias).
DEFAULT_HISTORY_DAYS = 45

# Limites de bom senso para o cadastro da conta (pegam erro de digitação, não substituem o banco).
MAX_BILL_TOTAL = Decimal("50000")
MAX_BILL_M3 = Decimal("2000")


def _parse_bill_month(text: str) -> date | None:
    """Aceita AAAA-MM (ou AAAA-MM-DD) e devolve o dia 1 desse mês; None se for inválido."""
    match = re.fullmatch(r"\s*(\d{4})-(\d{2})(?:-\d{2})?\s*", text or "")
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), 1)
    except ValueError:
        return None


def validate_last_bill(
    month: str, total_value: Any, m3_value: Any, today: date
) -> tuple[dict | None, tuple[date, Decimal, Decimal] | None]:
    """Valida os dados da conta; devolve (erro, None) ou (None, (mês, total, m³))."""
    bill_month = _parse_bill_month(month)
    if bill_month is None:
        return {"status": "error", "message": "Mês inválido. Use o formato AAAA-MM, por exemplo 2026-10."}, None
    if bill_month > today.replace(day=1):
        return {"status": "error", "message": "O mês da conta não pode ser futuro."}, None
    total, m3 = _bill_amount(total_value), _bill_amount(m3_value)
    if total is None or m3 is None:
        return {"status": "error", "message": "Os valores da conta devem ser números maiores ou iguais a zero."}, None
    if total > MAX_BILL_TOTAL or m3 > MAX_BILL_M3:
        return {
            "status": "error",
            "message": "Os valores parecem fora do normal para uma conta residencial. Peça ao usuário para conferir.",
        }, None
    return None, (bill_month, total, m3)


def write_last_bill(user_id: int, bill_month: date, total: Decimal, m3: Decimal) -> dict:
    """Grava a conta e traduz o resultado em um status seguro (ok, conflict ou error)."""
    try:
        saved = db_postgres.register_last_water_bill(user_id, bill_month, total, m3)
    except LastWaterBillConflictError:
        return {
            "status": "conflict",
            "message": "Já existe uma conta registrada para esse mês. Alterações de uma conta já registrada são feitas pelo aplicativo.",
        }
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    except DatabaseAccessError:
        return {
            "status": "error",
            "message": "Não foi possível gravar agora. Nada foi registrado; tente novamente.",
        }
    return {"status": "ok", "saved": _serialize(saved)}


def _bill_amount(value: Any) -> Decimal | None:
    """Valor com 2 casas; None se não for número finito maior ou igual a zero."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    amount = Decimal(str(value)).quantize(Decimal("0.01"))
    return amount if amount >= 0 else None


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


def build_tools(user_id: int, today: date, access_kind: str | None = None) -> list[BaseTool]:
    """Cria as tools já amarradas a user_id e à data de referência.

    O user_id NUNCA é um argumento exposto ao LLM — ele não pode inventá-lo.
    """
    validate_user_id(user_id)

    # Memória desta pergunta: o conjunto de tools nasce a cada execução do agente.
    memo_units: list[list] = []

    def _org_units() -> list:
        if not memo_units:
            memo_units.append(list(db_postgres.get_user_organization_properties(user_id)))
        return list(memo_units[0])

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
        kind = access_kind or db_postgres.get_user_access_kind(user_id)
        if kind != "organizational":
            return kind, None, None

        all_props = _org_units()
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

    def _history(kind: str, ids: list[int] | None, days: int) -> list[Any]:
        """Histórico de consumo: MongoDB primeiro e, se a telemetria estiver indisponível, a view
        diária do PostgreSQL. Documento inválido não troca de fonte."""
        # A autorização vem do PostgreSQL: se ele falhar aqui, não é indisponibilidade do MongoDB.
        devices = [] if kind == "residential" else db_postgres.get_authorized_device_ids(user_id, ids or [])
        try:
            if kind == "residential":
                return db_mongo.get_consumption_history(user_id, days)
            return [
                dataclasses.replace(point, user_id=user_id)
                for point in db_mongo.get_consumption_history_by_devices(devices, days)
            ]
        except DatabaseDataError:
            raise
        except (DatabaseAccessError, ConfigurationError) as exc:
            logger.warning(
                "Telemetria MongoDB indisponível (%s); usando dw.vw_ft_consumption_daily.",
                type(exc).__name__,
            )
            if kind == "residential":
                return db_postgres.get_residential_consumption_history(user_id, days, today)
            return db_postgres.get_organization_consumption_history(user_id, ids or [], days, today)

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
            return {"status": "ok", "can_estimate": db_postgres.organization_can_estimate(user_id, ids)}
        return _scope_error_response(kind, candidates)

    @tool
    def get_last_bill(property_name: str | None = None) -> dict:
        """Última conta de água registrada do usuário (tb_last_water_bill),
        ou o equivalente organizacional (último período faturado nas unidades
        da organização, calculado a partir da telemetria real).

        Serve como referência somente quando não há nenhuma leitura de consumo.
        Para estimar, use calculate_forecast: histórico curto ou ausência de tarifa
        não autorizam trocar o histórico pela conta anterior. A consulta explícita
        da última conta continua disponível, independentemente da previsão.

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
            bill = db_postgres.get_organization_last_billed_period(user_id, ids, today)
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
        if invalid := days_error(days):
            return invalid
        kind, ids, candidates = _resolve_scope(property_name)
        if kind in ("residential", "organizational"):
            points = _history(kind, ids, days)
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
        """Meta diária de consumo de uma conta residencial.

        Para organização, use `calculate_forecast`, que agrega a meta mensal
        cadastrada para todas as unidades autorizadas (ou para a unidade
        mencionada). Não use a preferência residencial como meta da organização.
        """
        kind = access_kind or db_postgres.get_user_access_kind(user_id)
        if kind == "organizational":
            return {
                "status": "not_applicable",
                "message": "Para organizações, a meta é mensal e deve ser consultada junto da previsão das unidades.",
            }
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
            rate = db_postgres.get_organization_effective_rate(user_id, ids, today)
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
        não houver nenhuma leitura; projeção x tarifa se houver), tendência
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
        if invalid := days_error(history_days, "history_days"):
            return invalid
        kind, ids, candidates = _resolve_scope(property_name)
        if kind not in ("residential", "organizational"):
            return _scope_error_response(kind, candidates)

        can_estimate = (
            db_postgres.user_can_estimate(user_id)
            if kind == "residential"
            else db_postgres.organization_can_estimate(user_id, ids)
        )
        if not can_estimate:
            return {
                "status": "insufficient_data",
                "message": (
                    "Sem cadastro suficiente para estimativas. Nenhum cálculo foi executado."
                ),
            }

        history = _history(kind, ids, history_days)

        if kind == "residential":
            daily_target = db_mongo.get_daily_liters_target(user_id)
            last_bill = db_postgres.get_last_water_bill(user_id) if not history else None
            region_id = db_postgres.get_user_region_id(user_id)
            classification_id = db_postgres.get_user_property_classification_id(user_id)
            region_rate: Decimal | None = None
            if region_id is not None and classification_id is not None:
                try:
                    region_rate = db_postgres.get_current_region_rate(region_id, classification_id, today)
                except RegionRateNotFound:
                    region_rate = None
        else:
            try:
                monthly_target = db_postgres.get_organization_monthly_target(user_id, ids or [])
            except DatabaseAccessError as exc:
                # A indisponibilidade da view de metas não deve transformar a
                # projeção em erro nem inventar uma meta para a organização.
                logger.warning("Não foi possível consultar as metas mensais organizacionais (%s).", type(exc).__name__)
                monthly_target = None
            daily_target = (
                monthly_target / calendar.monthrange(today.year, today.month)[1]
                if monthly_target
                else None
            )
            last_bill = (
                db_postgres.get_organization_last_billed_period(user_id, ids, today)
                if not history else None
            )
            region_rate = db_postgres.get_organization_effective_rate(user_id, ids, today)

        if not history and last_bill is None:
            unavailable: dict[str, object] = {
                "status": "insufficient_data",
                "message": (
                    "Não há leituras de consumo nem uma conta anterior disponíveis para calcular "
                    "uma projeção confiável."
                ),
                "scope": "all_authorized_units" if kind == "organizational" else "residential_property",
            }
            if kind == "organizational":
                unavailable["property_count"] = len(ids or [])
                unavailable["monthly_target_liters"] = monthly_target
                unavailable["target_risk"] = {
                    "assessable": False,
                    "at_risk": False,
                    "monthly_target_liters": monthly_target,
                    "month_projection_liters": None,
                    "difference_pct": None,
                }
            return unavailable

        result = calc.calculate_full_forecast(
            can_estimate=can_estimate,
            history=history,
            last_bill=last_bill,
            region_rate=region_rate,
            daily_target=daily_target,
            today=today,
        )
        return {"status": "ok", "forecast": _serialize(result)}

    @tool
    def get_habit_baseline() -> dict:
        """Litros esperados por semana e por mês dos hábitos cadastrados do usuário.

        Use para explicar de onde pode vir parte do consumo (ex.: lavar carro às
        segundas) ou como base de uma simulação de mudança de hábito. Os valores são
        médias de referência (ou o valor do cadastro), não medições do hidrômetro,
        e não fazem parte do cálculo da previsão. Disponível só para conta
        residencial; sem hábitos cadastrados, devolve insufficient_data.
        """
        kind = access_kind or db_postgres.get_user_access_kind(user_id)
        if kind != "residential":
            return {
                "status": "not_applicable",
                "message": "Hábitos estão disponíveis apenas para contas residenciais.",
            }
        habits = db_postgres.get_user_habits(user_id)
        if not habits:
            return {"status": "insufficient_data", "message": "Nenhum hábito cadastrado."}
        return {
            "status": "ok",
            **summarize_habit_baseline(habits),
            "note": "Estimativa por média de referência; não é medição nem parte da previsão.",
        }

    @tool
    def simulate_consumption_change(
        change_pct: float, days: int = 30, property_name: str | None = None
    ) -> dict:
        """Simula "e se o consumo diário mudasse X%" e compara com o cenário atual.

        change_pct: variação percentual do consumo diário. Use número negativo para
          redução (ex.: -10 para "cair 10%") e positivo para aumento.
        days: período da comparação em dias (padrão 30).

        A base é a média diária recente do próprio usuário (a mesma do cálculo de
        previsão), buscada pela ferramenta. Retorna base e cenário por dia e no
        período, a diferença em litros e as hipóteses usadas. É uma simulação, não
        uma previsão nem uma medição. Sem histórico suficiente, devolve
        insufficient_data e não calcula nada.

        Use property_name somente se o usuário mencionar uma unidade específica da
        organização pelo nome ou endereço; em branco, usa a organização toda.
        """
        if invalid := days_error(days, "days"):
            return invalid
        forecast_result = calculate_forecast.invoke({"property_name": property_name})
        if forecast_result.get("status") != "ok":
            return forecast_result
        forecast = forecast_result["forecast"]
        if not forecast.get("has_enough_history"):
            return {
                "status": "insufficient_data",
                "message": "Histórico de consumo insuficiente para simular com segurança.",
            }
        baseline = (forecast.get("projection") or {}).get("daily_average_liters")
        try:
            scenario = simulate_percentage_change(float(baseline or 0), change_pct, days)
        except ValueError as exc:
            return {"status": "error", "message": str(exc)}
        return {
            "status": "ok",
            "scenario": dataclasses.asdict(scenario),
            "assumptions": [
                "Base: média diária dos dias recentes com registro (a mesma usada na previsão).",
                f"Variação aplicada de forma uniforme a todos os {days} dias.",
                "Não considera sazonalidade, clima nem mudança de hábitos além da variação informada.",
                "Simulação: não é previsão nem medição do hidrômetro.",
            ],
        }

    @tool
    def simulate_target_change(new_daily_target: float, property_name: str | None = None) -> dict:
        """Simula "e se eu mudasse minha meta diária para X litros": o risco de passar da meta.

        new_daily_target: nova meta diária em litros (maior que zero).

        Usa a mesma projeção do mês da previsão e compara o risco com a meta atual e com
        a simulada. É uma simulação: não altera a meta cadastrada no app. Sem meta atual
        cadastrada, só mostra o resultado da meta simulada. Sem histórico suficiente, não simula.

        Use property_name somente se o usuário mencionar uma unidade específica da organização.
        """
        forecast_result = calculate_forecast.invoke({"property_name": property_name})
        if forecast_result.get("status") != "ok":
            return forecast_result
        forecast = forecast_result["forecast"]
        projection = (forecast.get("projection") or {}).get("month_projection_liters")
        if not forecast.get("has_enough_history") or projection is None:
            return {
                "status": "insufficient_data",
                "message": "Histórico de consumo insuficiente para simular a meta com segurança.",
            }
        current_target = (forecast.get("target_risk") or {}).get("monthly_target_liters")
        days = calc._days_in_month(today)
        try:
            comparison = calc.compare_target_change(
                float(projection), current_target / days if current_target else None,
                new_daily_target, today,
            )
        except ValueError as exc:
            return {"status": "error", "message": str(exc)}
        return {
            "status": "ok",
            "comparison": _serialize(comparison),
            "assumptions": [
                "A projeção do mês é a mesma da previsão; só a meta muda.",
                "Simulação: a meta cadastrada no app não foi alterada.",
            ],
        }

    @tool
    def get_investment_scenarios(property_name: str | None = None) -> dict:
        """Cenários de investimento em economia de água (aeradores, reúso, captação de chuva...).

        Traz, de cada cenário cadastrado, o valor do investimento, a redução esperada (%), a
        economia anual em reais e o prazo de retorno em meses. Quando há média diária de consumo,
        acrescenta a estimativa de litros economizados por ano com aquela redução. Os valores do
        cadastro são de referência: não prometa economia garantida. Só para conta de organização.

        Use property_name somente se o usuário mencionar uma unidade específica.
        """
        kind, ids, candidates = _resolve_scope(property_name)
        if kind != "organizational":
            if kind == "residential":
                return {
                    "status": "not_applicable",
                    "message": "Cenários de investimento estão disponíveis para contas de organização.",
                }
            return _scope_error_response(kind, candidates)
        scenarios = db_postgres.get_investment_scenarios(user_id)
        if not scenarios:
            return {"status": "insufficient_data", "message": "Nenhum cenário de investimento cadastrado."}
        daily_average = None
        forecast_result = calculate_forecast.invoke({"property_name": property_name})
        if forecast_result.get("status") == "ok" and forecast_result["forecast"].get("has_enough_history"):
            daily_average = (forecast_result["forecast"].get("projection") or {}).get("daily_average_liters")
        for scenario in scenarios:
            scenario["estimated_liters_saved_per_year"] = (
                calc.estimate_investment_savings(float(daily_average), scenario["reduction_pct"])
                if daily_average
                else None
            )
        return {
            "status": "ok",
            "scenarios": scenarios,
            "note": "Valores de referência do cadastro; a economia real depende da operação de cada unidade.",
        }

    @tool
    def register_last_bill(
        month: str, total_value: float, m3_value: float, confirmed: bool = False
    ) -> dict:
        """Registra a conta de água de um mês do usuário (tb_last_water_bill).

        Use somente quando o usuário pedir para registrar, cadastrar ou informar a
        última conta de água. Para apenas consultar, use get_last_bill.

        month: mês de referência da conta, no formato AAAA-MM (ex.: 2026-10).
        total_value: valor total da conta, em reais.
        m3_value: consumo da conta, em metros cúbicos (m³).
        confirmed: SEMPRE false na primeira chamada. A ferramenta então só devolve
          needs_confirmation com os dados; repita esses dados ao usuário e pergunte
          se pode salvar. Chame de novo com confirmed=true somente depois que o
          usuário responder que sim em uma mensagem posterior. Nunca grave sem essa
          confirmação, nunca invente valores e nunca use o que o usuário não disse.

        Não sobrescreve: se o mês já tem conta, devolve conflict. Só confirme o
        registro quando o status for ok (gravado no banco).

        Disponível apenas para usuários residenciais.
        """
        if (access_kind or db_postgres.get_user_access_kind(user_id)) != "residential":
            return {
                "status": "not_available",
                "message": "O cadastro da conta só está disponível para contas residenciais.",
            }
        error, parsed = validate_last_bill(month, total_value, m3_value, today)
        if error is not None:
            return error
        bill_month, total, m3 = parsed
        proposal = {"month": bill_month.isoformat(), "total_value": float(total), "m3_value": float(m3)}
        if get_settings().confirmation_interrupt_enabled:
            # Com a pausa do grafo ligada, quem grava é o código depois do "sim"; a ferramenta só propõe.
            return {
                "status": "pending_confirmation",
                "pending_write": {"kind": "register_last_bill", "params": proposal},
                "message": "Nada foi gravado. O sistema vai pedir a confirmação ao usuário; não faça a pergunta.",
            }
        if not confirmed:
            return {
                "status": "needs_confirmation",
                "proposal": proposal,
                "message": "Nada foi gravado. Repita os dados ao usuário e peça uma confirmação explícita (sim ou não).",
            }
        return write_last_bill(user_id, bill_month, total, m3)

    tools = [
        check_can_estimate,
        get_last_bill,
        get_consumption_history,
        get_daily_target,
        get_region_rate,
        calculate_forecast,
        get_habit_baseline,
        simulate_consumption_change,
        simulate_target_change,
        get_investment_scenarios,
    ]
    # Escrita desligada por padrão: sem a chave, o conjunto de tools é o de sempre.
    if get_settings().bill_registration_enabled:
        tools.append(register_last_bill)
    return tools
