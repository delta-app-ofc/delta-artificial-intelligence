"""Ferramentas de consulta e resumo do Agente de Consumo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from langchain_core.tools import BaseTool, tool
from pydantic import StrictInt

from app.config import ConfigurationError
from app.data import db_mongo, db_postgres
from app.tools.consumption import analysis
from app.tools.exceptions import DatabaseAccessError, DatabaseDataError
from app.tools.models import OrganizationProperty


@dataclass(frozen=True)
class _Scope:
    kind: str
    property_ids: tuple[int, ...] = ()
    units: tuple[OrganizationProperty, ...] = ()
    selected_unit: OrganizationProperty | None = None


@dataclass(frozen=True)
class _ReadResult:
    scope: _Scope
    period: analysis.ConsumptionPeriod
    aggregate: analysis.ConsumptionAggregate
    source: str
    granularity: str
    notes: tuple[str, ...]
    partial_data: bool | None


def _unit_data(unit: OrganizationProperty) -> dict[str, object]:
    return {
        "property_id": unit.property_id,
        "name": unit.name,
        "city": unit.city,
        "state": unit.state,
    }


def _scope_data(scope: _Scope) -> dict[str, object]:
    if scope.kind == "residential":
        return {
            "kind": "residential",
            "description": "Registros residenciais vinculados ao usuário.",
            "unit_selection": "residência do usuário; a fonte não mapeia registros por imóvel",
        }
    if scope.selected_unit is not None:
        return {"kind": "organizational", "unit": _unit_data(scope.selected_unit)}
    return {
        "kind": "organizational",
        "unit_selection": "todas as unidades autorizadas",
        "authorized_unit_count": len(scope.units),
    }


def _period_is_midnight(value: datetime) -> bool:
    return value.time().replace(tzinfo=None) == time.min


def _read_period(
    *,
    user_id: int,
    scope: _Scope,
    period: analysis.ConsumptionPeriod,
    as_of: datetime,
) -> _ReadResult:
    notes = list(period.notes)
    local_today = as_of.astimezone(ZoneInfo(period.timezone_name)).date()
    includes_today = period.start.date() <= local_today <= period.last_included_date
    if period.end <= period.start:
        notes.append("O período não contém tempo ou datas para consulta; não há registros a resumir.")
        if scope.kind == "residential":
            aggregate = analysis.aggregate_windows(
                [], period=period, user_id=user_id, as_of=as_of
            )
            return _ReadResult(
                scope=scope,
                period=period,
                aggregate=aggregate,
                source="MongoDB consumption_summary",
                granularity="janelas armazenadas, agrupadas pelo dia local de início",
                notes=tuple(notes),
                partial_data=None,
            )
        aggregate = analysis.aggregate_daily_records([], period=period)
        return _ReadResult(
            scope=scope,
            period=period,
            aggregate=aggregate,
            source="PostgreSQL dw.vw_ft_consumption_daily",
            granularity="consolidado diário por unidade",
            notes=tuple(notes),
            partial_data=None,
        )
    if scope.kind == "residential":
        if includes_today:
            notes.append(
                "O dia de hoje está parcial até o instante da consulta; janelas ainda não finalizadas foram excluídas."
            )
        start_utc, end_utc = analysis.utc_bounds(period)
        as_of_utc = as_of.astimezone(timezone.utc)
        points = db_mongo.get_consumption_history_between(
            user_id, start_utc, end_utc, as_of_utc
        )
        aggregate = analysis.aggregate_windows(
            points, period=period, user_id=user_id, as_of=as_of_utc
        )
        if aggregate.windows_crossing_local_midnight:
            notes.append(
                "Janelas que cruzam a meia-noite foram atribuídas ao dia local do início; "
                "o volume não foi rateado."
            )
        if aggregate.windows_crossing_period_end:
            notes.append(
                "Há janelas iniciadas no recorte que terminaram depois do fim exclusivo; "
                "o volume foi atribuído pelo horário de início."
            )
        if aggregate.has_gaps_between_recorded_days:
            notes.append(
                "Há datas sem registro entre os primeiros e últimos dias com medições; "
                "elas não foram preenchidas com zero."
            )
        return _ReadResult(
            scope=scope,
            period=period,
            aggregate=aggregate,
            source="MongoDB consumption_summary",
            granularity="janelas armazenadas, agrupadas pelo dia local de início",
            notes=tuple(notes),
            partial_data=(
                True
                if includes_today
                or aggregate.windows_crossing_local_midnight
                or aggregate.windows_crossing_period_end
                else None
            ),
        )

    bounds = analysis.daily_date_bounds(period)
    records = (
        db_postgres.get_organization_consumption_daily(
            list(scope.property_ids), bounds[0], bounds[1]
        )
        if bounds is not None
        else []
    )
    aggregate = analysis.aggregate_daily_records(records, period=period)
    if not _period_is_midnight(period.start) or not _period_is_midnight(period.end):
        notes.append(
            "A fonte SQL contém dias completos; nas bordas do recorte móvel, "
            "o filtro inclui as datas inteiras e não distribui volumes por horário."
        )
    if includes_today:
        notes.append(
            "O consolidado diário de hoje pode estar parcial ou desatualizado; "
            "a fonte não informa o horário da última atualização."
        )
    notes.append(
        "A view não garante cadência ou cobertura contínua; a ausência de linha não "
        "significa consumo zero e pode decorrer de dados ainda não carregados no ETL."
    )
    if aggregate.has_gaps_between_recorded_days:
        notes.append(
            "Há datas sem registro entre os primeiros e últimos dias disponíveis; "
            "elas não foram preenchidas com zero."
        )
    return _ReadResult(
        scope=scope,
        period=period,
        aggregate=aggregate,
        source="PostgreSQL dw.vw_ft_consumption_daily",
        granularity="consolidado diário por unidade",
        notes=tuple(notes),
        partial_data=(
            True
            if not _period_is_midnight(period.start)
            or not _period_is_midnight(period.end)
            or includes_today
            else None
        ),
    )


def _metadata(result: _ReadResult) -> dict[str, object]:
    first_day = result.period.start.date()
    last_day = result.period.last_included_date
    recorded_days = {item.day for item in result.aggregate.daily_totals}
    dates_without_records = [
        (first_day + timedelta(days=offset)).isoformat()
        for offset in range(max(0, (last_day - first_day).days + 1))
        if first_day + timedelta(days=offset) not in recorded_days
    ]
    partial_data = True if dates_without_records else result.partial_data
    return {
        "source": result.source,
        "period": result.period.as_dict(),
        "timezone": result.period.timezone_name,
        "granularity": result.granularity,
        "unit": "litros",
        "scope": _scope_data(result.scope),
        "data_quality": {
            "partial_data": partial_data,
            "coverage": "não determinada",
            "dates_without_records": dates_without_records,
            "days_without_records": len(dates_without_records),
            "notes": list(result.notes)
            + [
                "Dias com registros não comprovam cobertura contínua; a média usa somente "
                "esses dias."
            ],
        },
    }


def _scope_failure(status: str, message: str, **details: object) -> dict[str, object]:
    return {"status": status, "message": message, **details}


def build_tools(
    user_id: int,
    *,
    clock: Callable[[], datetime] | None = None,
    timezone_name: str = analysis.DEFAULT_TIMEZONE,
) -> list[BaseTool]:
    """Cria ferramentas com o ``user_id`` confiável preso às funções.

    O identificador nunca aparece nos argumentos enviados pelo modelo.
    """
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise ValueError("user_id deve ser um inteiro positivo recebido do chamador.")

    now_provider = clock or (lambda: datetime.now(timezone.utc))

    def _scope(
        unit_name: str | None, unit_id: int | None
    ) -> tuple[_Scope | None, dict[str, object] | None]:
        needle = (unit_name or "").strip().casefold()
        if unit_name is not None and not needle:
            raise analysis.InvalidConsumptionInput("O nome da unidade não pode estar vazio.")
        if unit_id is not None and (
            isinstance(unit_id, bool) or not isinstance(unit_id, int) or unit_id <= 0
        ):
            raise analysis.InvalidConsumptionInput("O identificador da unidade não é válido.")

        kind = db_postgres.get_user_access_kind(user_id)
        if kind == "residential":
            if needle or unit_id is not None:
                return None, _scope_failure(
                    "insufficient_data",
                    "A fonte residencial não associa os registros de consumo a um imóvel específico.",
                    source="MongoDB consumption_summary",
                    timezone=timezone_name,
                )
            return _Scope(kind="residential"), None
        if kind == "none":
            return None, _scope_failure(
                "insufficient_data",
                "Não há residência ou organização vinculada ao usuário.",
                timezone=timezone_name,
            )
        if kind != "organizational":
            return None, _scope_failure(
                "insufficient_data",
                "Não foi possível identificar um escopo autorizado de consumo.",
                timezone=timezone_name,
            )

        units = tuple(db_postgres.get_user_organization_properties(user_id))
        if not units:
            return None, _scope_failure(
                "insufficient_data",
                "Não há unidades organizacionais autorizadas com endereço disponível.",
                source="PostgreSQL tb_user_organization",
                timezone=timezone_name,
            )
        if not needle and unit_id is None:
            return _Scope(
                kind="organizational",
                property_ids=tuple(unit.property_id for unit in units),
                units=units,
            ), None

        candidates = (
            tuple(unit for unit in units if unit.property_id == unit_id)
            if unit_id is not None
            else units
        )
        if not candidates:
            return None, _scope_failure(
                "insufficient_data",
                "O identificador informado não pertence às unidades autorizadas do usuário.",
                source="PostgreSQL tb_user_organization",
                available_units=[_unit_data(unit) for unit in units],
                timezone=timezone_name,
            )
        if not needle:
            matches = candidates
        else:
            exact_matches = tuple(
                unit for unit in candidates if unit.name.strip().casefold() == needle
            )
            matches = exact_matches or tuple(
                unit for unit in candidates if needle in unit.name.casefold()
            )
        if not matches:
            return None, _scope_failure(
                "insufficient_data",
                "Nenhuma unidade autorizada corresponde ao nome informado; nenhuma consulta de consumo foi feita.",
                source="PostgreSQL tb_user_organization",
                available_units=[_unit_data(unit) for unit in candidates],
                timezone=timezone_name,
            )
        if len(matches) > 1:
            return None, _scope_failure(
                "ambiguous",
                "Mais de uma unidade autorizada corresponde ao nome; escolha uma delas.",
                candidates=[_unit_data(unit) for unit in matches],
                source="PostgreSQL tb_user_organization",
                timezone=timezone_name,
            )
        selected = matches[0]
        return _Scope(
            kind="organizational",
            property_ids=(selected.property_id,),
            units=(selected,),
            selected_unit=selected,
        ), None

    def _prepare(
        period_name: str,
        start_date: str | None,
        end_date: str | None,
        unit_name: str | None,
        unit_id: int | None,
    ) -> _ReadResult | dict[str, object]:
        as_of = now_provider()
        period = analysis.resolve_period(
            period_name,
            now=as_of,
            timezone_name=timezone_name,
            start_date=start_date,
            end_date=end_date,
        )
        scope, error = _scope(unit_name, unit_id)
        if error is not None:
            return error
        assert scope is not None
        return _read_period(
            user_id=user_id,
            scope=scope,
            period=period,
            as_of=as_of,
        )

    def _run_safely(action: Callable[[], dict[str, object]]) -> dict[str, object]:
        try:
            return action()
        except analysis.InvalidConsumptionInput as exc:
            return _scope_failure(
                "invalid_input", str(exc), timezone=timezone_name
            )
        except (analysis.InconsistentConsumptionData, DatabaseDataError):
            return _scope_failure(
                "inconsistent_data",
                "A fonte retornou medições inconsistentes; os valores não foram agregados.",
                timezone=timezone_name,
            )
        except (DatabaseAccessError, ConfigurationError):
            return _scope_failure(
                "source_unavailable",
                "Não foi possível consultar a fonte de consumo configurada.",
                timezone=timezone_name,
            )

    def _summary_result(result: _ReadResult) -> dict[str, object]:
        return {
            "status": "ok" if result.aggregate.has_data else "insufficient_data",
            **_metadata(result),
            "metrics": result.aggregate.summary_dict(),
            "daily_consumption": [
                {"date": item.day.isoformat(), "liters": item.liters}
                for item in result.aggregate.daily_totals
            ],
        }

    @tool
    def get_consumption_summary(
        period: analysis.PeriodName = "last_30_days",
        start_date: str | None = None,
        end_date: str | None = None,
        unit_name: str | None = None,
        unit_id: StrictInt | None = None,
    ) -> dict:
        """Resume consumo registrado num período e escopo autorizados.

        Use os períodos today, yesterday, this_week, this_month, last_7_days
        ou last_30_days. Para datas informadas pelo usuário, use period='custom'
        com início e fim inclusivos no formato AAAA-MM-DD. O fuso configurado
        (America/Sao_Paulo por padrão) usa limite final exclusivo. O histórico
        usa últimos 30 dias. Para organização, unit_name seleciona uma unidade
        vinculada ao usuário; use unit_id para distinguir unidades com nomes
        iguais. Sem seleção, soma todas as unidades autorizadas. Respostas
        incluem litros, dias com registro e média por esses dias; datas sem
        registro nunca viram zero.
        """
        def summary() -> dict[str, object]:
            result = _prepare(period, start_date, end_date, unit_name, unit_id)
            if isinstance(result, dict):
                return result
            return _summary_result(result)

        return _run_safely(summary)

    @tool
    def compare_consumption_periods(
        current_period: analysis.PeriodName = "last_7_days",
        previous_period: analysis.PeriodName = "previous_7_days",
        current_start_date: str | None = None,
        current_end_date: str | None = None,
        previous_start_date: str | None = None,
        previous_end_date: str | None = None,
        unit_name: str | None = None,
        unit_id: StrictInt | None = None,
    ) -> dict:
        """Compara dois períodos consultados no mesmo escopo autorizado.

        Use last_7_days com previous_7_days, last_30_days com previous_30_days
        ou this_month com previous_month_same_days. Períodos customizados
        aceitam datas inclusivas separadas para cada lado. A diferença é atual
        menos anterior; a variação percentual fica indisponível quando o total
        anterior registrado é zero. Cada período limita-se a 366 dias.
        """

        def compare() -> dict[str, object]:
            as_of = now_provider()
            current = analysis.resolve_period(
                current_period,
                now=as_of,
                timezone_name=timezone_name,
                start_date=current_start_date,
                end_date=current_end_date,
            )
            previous = analysis.resolve_period(
                previous_period,
                now=as_of,
                timezone_name=timezone_name,
                start_date=previous_start_date,
                end_date=previous_end_date,
            )
            scope, error = _scope(unit_name, unit_id)
            if error is not None:
                return error
            assert scope is not None
            current_result = _read_period(
                user_id=user_id, scope=scope, period=current, as_of=as_of
            )
            previous_result = _read_period(
                user_id=user_id, scope=scope, period=previous, as_of=as_of
            )
            both_have_data = (
                current_result.aggregate.has_data and previous_result.aggregate.has_data
            )
            comparison_notes: list[str] = []
            current_duration = (current.end - current.start).total_seconds()
            previous_duration = (previous.end - previous.start).total_seconds()
            if current_duration != previous_duration:
                comparison_notes.append(
                    "Os períodos têm durações diferentes; compare os totais considerando esses limites."
                )
            if current.calendar_days != previous.calendar_days:
                comparison_notes.append(
                    "Os períodos abrangem quantidades diferentes de datas locais."
                )
            if (
                current_result.aggregate.days_with_records
                != previous_result.aggregate.days_with_records
            ):
                comparison_notes.append(
                    "Os períodos têm quantidades diferentes de dias com registros; os totais usam dias observados em cada lado."
                )
            if previous_period == "previous_month_same_days" and (
                previous.calendar_days < current.calendar_days
            ):
                comparison_notes.append(
                    "O mês anterior tem menos dias; o período anterior foi limitado ao último dia daquele mês."
                )
            current_metadata = _metadata(current_result)
            previous_metadata = _metadata(previous_result)
            return {
                "status": "ok" if both_have_data else "insufficient_data",
                "source": current_result.source,
                "timezone": timezone_name,
                "unit": "litros",
                "scope": _scope_data(scope),
                "current": {
                    "period": current.as_dict(),
                    "duration_seconds": current_duration,
                    "granularity": current_result.granularity,
                    "metrics": current_result.aggregate.summary_dict(),
                    "data_quality": current_metadata["data_quality"],
                },
                "previous": {
                    "period": previous.as_dict(),
                    "duration_seconds": previous_duration,
                    "granularity": previous_result.granularity,
                    "metrics": previous_result.aggregate.summary_dict(),
                    "data_quality": previous_metadata["data_quality"],
                },
                "comparison": analysis.compare_aggregates(
                    current_result.aggregate, previous_result.aggregate
                ),
                "comparison_notes": comparison_notes,
            }

        return _run_safely(compare)

    @tool
    def get_consumption_peaks(
        period: analysis.PeriodName = "last_30_days",
        start_date: str | None = None,
        end_date: str | None = None,
        unit_name: str | None = None,
        unit_id: StrictInt | None = None,
        limit: StrictInt = 5,
    ) -> dict:
        """Lista os maiores totais diários registrados, em ordem estável.

        Use quando o usuário perguntar por picos ou dias de maior consumo. O
        padrão usa últimos 30 dias; datas customizadas são inclusivas. Limit
        deve ficar entre 1 e 10. A ferramenta só mede pico diário, não vazão
        horária; janelas residenciais são agrupadas pelo dia de início local.
        """

        def peaks() -> dict[str, object]:
            analysis.validate_peak_limit(limit)
            result = _prepare(period, start_date, end_date, unit_name, unit_id)
            if isinstance(result, dict):
                return result
            items, tied_for_highest, tie_truncated = analysis.peak_days(
                result.aggregate, limit
            )
            return {
                "status": "ok" if result.aggregate.has_data else "insufficient_data",
                **_metadata(result),
                "ranking": items,
                "tie_breaker": "maior total primeiro; datas crescentes em empate",
                "days_tied_for_highest": tied_for_highest,
                "highest_tie_truncated_by_limit": tie_truncated,
            }

        return _run_safely(peaks)

    @tool
    def list_consumption_units() -> dict:
        """Lista nomes de unidades organizacionais autorizadas ao usuário.

        Use para esclarecer uma unidade ambígua ou permitir comparação entre
        unidades organizacionais. Nunca retorna imóveis de outros usuários.
        A fonte residencial não mapeia os documentos Mongo a property_id; nesse
        caminho a listagem por imóvel não está disponível.
        """

        def list_units() -> dict[str, object]:
            kind = db_postgres.get_user_access_kind(user_id)
            if kind == "residential":
                return _scope_failure(
                    "insufficient_data",
                    "A telemetria residencial não identifica imóveis individualmente.",
                    source="MongoDB consumption_summary",
                    timezone=timezone_name,
                )
            if kind != "organizational":
                return _scope_failure(
                    "insufficient_data",
                    "Não há organização vinculada ao usuário.",
                    timezone=timezone_name,
                )
            units = db_postgres.get_user_organization_properties(user_id)
            if not units:
                return _scope_failure(
                    "insufficient_data",
                    "Não há unidades organizacionais autorizadas disponíveis.",
                    source="PostgreSQL tb_user_organization",
                    timezone=timezone_name,
                )
            return {
                "status": "ok",
                "source": "PostgreSQL tb_user_organization",
                "timezone": timezone_name,
                "scope": {"kind": "organizational", "user_id_bound": True},
                "units": [_unit_data(unit) for unit in units],
            }

        return _run_safely(list_units)

    return [
        get_consumption_summary,
        compare_consumption_periods,
        get_consumption_peaks,
        list_consumption_units,
    ]
