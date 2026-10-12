from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Iterator, Literal

import psycopg2
from psycopg2.extensions import parse_dsn

from app.config import (
    get_postgres_connection_args,
    get_settings,
)
from app.tools.exceptions import (
    DatabaseConnectionError,
    DatabaseQueryError,
    RegionRateNotFound,
)
from app.tools.models import ConsumptionPoint, LastWaterBill, OrganizationProperty


def get_conn():
    settings = get_settings()
    connection_args = get_postgres_connection_args(settings=settings)
    query_timeout_ms = settings.db_query_timeout_seconds * 1000
    statement_timeout_option = f"-c statement_timeout={query_timeout_ms}ms"

    try:
        existing_options = ""
        if "dsn" in connection_args:
            existing_options = parse_dsn(connection_args["dsn"]).get("options", "")
        options = " ".join(
            value for value in (existing_options, statement_timeout_option) if value
        )
        connection_args["options"] = options
    except psycopg2.Error as exc:
        raise DatabaseConnectionError("PostgreSQL") from exc

    try:
        return psycopg2.connect(**connection_args)
    except psycopg2.Error as exc:
        raise DatabaseConnectionError("PostgreSQL") from exc


def _query_error(exc: psycopg2.Error) -> DatabaseQueryError:
    return DatabaseQueryError(
        "PostgreSQL",
        code=getattr(exc, "pgcode", None),
    )


def _cleanup_error(exc: Exception) -> DatabaseQueryError:
    if isinstance(exc, psycopg2.Error):
        return _query_error(exc)
    return DatabaseQueryError("PostgreSQL")


@contextmanager
def _cursor() -> Iterator:
    """Abre e fecha cursor/conexão, protegendo mensagens do driver."""
    conn = get_conn()
    cur = None
    operation_failed = False
    try:
        try:
            cur = conn.cursor()
        except psycopg2.Error as exc:
            operation_failed = True
            raise _query_error(exc) from exc
        except BaseException:
            operation_failed = True
            raise

        try:
            yield cur
        except psycopg2.Error as exc:
            operation_failed = True
            raise _query_error(exc) from exc
        except BaseException:
            operation_failed = True
            raise
    finally:
        cleanup_error = None
        try:
            if cur is not None:
                cur.close()
        except Exception as exc:
            cleanup_error = exc
        finally:
            try:
                conn.close()
            except Exception as exc:
                if cleanup_error is None:
                    cleanup_error = exc

        if cleanup_error is not None and not operation_failed:
            raise _cleanup_error(cleanup_error) from cleanup_error


def check_connection() -> None:
    """Confirma acesso ao banco com uma consulta que não depende do schema."""
    with _cursor() as cur:
        cur.execute("SELECT 1;")
        row = cur.fetchone()

    if row != (1,):
        raise DatabaseQueryError("PostgreSQL")


def user_can_estimate(user_id: int) -> bool:
    with _cursor() as cur:
        cur.execute("SELECT fn_user_can_estimate(%s);", (user_id,))
        row = cur.fetchone()
    return bool(row[0]) if row is not None else False


def get_user_region_id(user_id: int) -> int | None:
    with _cursor() as cur:
        cur.execute(
            """
            SELECT a.region_id
              FROM tb_user_property up
              JOIN tb_property p ON p.id = up.property_id
              JOIN tb_address  a ON a.id = p.address_id
             WHERE up.user_id = %s
             ORDER BY up.id
             LIMIT 1;
            """,
            (user_id,),
        )
        row = cur.fetchone()
    return int(row[0]) if row is not None else None


def get_user_property_classification_id(user_id: int) -> int | None:
    with _cursor() as cur:
        cur.execute(
            """
            SELECT p.classification_id
              FROM tb_user_property up
              JOIN tb_property p ON p.id = up.property_id
             WHERE up.user_id = %s
             ORDER BY up.id
             LIMIT 1;
            """,
            (user_id,),
        )
        row = cur.fetchone()
    return int(row[0]) if row is not None else None


def get_current_region_rate(region_id: int, classification_id: int, on_date: date) -> Decimal:
    missing_rate_message = (
        f"Sem tarifa vigente para a região {region_id}, categoria "
        f"{classification_id} em {on_date}."
    )
    with _cursor() as cur:
        try:
            cur.execute(
                "SELECT fn_get_current_region_rate(%s, %s, %s);",
                (region_id, classification_id, on_date),
            )
        except psycopg2.errors.RaiseException as exc:  # type: ignore[attr-defined]
            raise RegionRateNotFound(
                missing_rate_message
            ) from exc
        row = cur.fetchone()
        if row is None or row[0] is None:
            raise RegionRateNotFound(missing_rate_message)
        return Decimal(str(row[0]))


def get_last_water_bill(user_id: int) -> LastWaterBill | None:
    with _cursor() as cur:
        cur.execute(
            """
            SELECT user_id, month, total_value, m3_value
              FROM tb_last_water_bill
             WHERE user_id = %s
             ORDER BY month DESC
             LIMIT 1;
            """,
            (user_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return LastWaterBill(
        user_id=int(row[0]),
        month=row[1],
        total_value=Decimal(str(row[2])),
        m3_value=Decimal(str(row[3])),
    )


def get_user_access_kind(user_id: int) -> Literal["residential", "organizational", "none"]:
    """Resolve como o usuário se relaciona com propriedades.

    Prioridade: se o usuário tem qualquer linha em tb_user_property, é tratado
    como residencial (caminho antigo, inalterado). Só verifica
    tb_user_organization quando não há nenhuma propriedade residencial.
    """
    with _cursor() as cur:
        cur.execute("SELECT 1 FROM tb_user_property WHERE user_id = %s LIMIT 1;", (user_id,))
        if cur.fetchone() is not None:
            return "residential"
        cur.execute("SELECT 1 FROM tb_user_organization WHERE user_id = %s LIMIT 1;", (user_id,))
        if cur.fetchone() is not None:
            return "organizational"
        return "none"


def get_user_organization_properties(user_id: int) -> list[OrganizationProperty]:
    """Todas as propriedades de todas as organizações vinculadas ao usuário
    (tb_user_organization é M:N; não há papel/hierarquia, então todas as
    organizações do usuário entram no mesmo conjunto agregável)."""
    with _cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT p.id, p.name, a.city, a.state
              FROM tb_user_organization uo
              JOIN tb_property p ON p.organization_id = uo.organization_id
              JOIN tb_address  a ON a.id = p.address_id
             WHERE uo.user_id = %s
             ORDER BY p.id;
            """,
            (user_id,),
        )
        rows = cur.fetchall()
    return [
        OrganizationProperty(property_id=row[0], name=row[1], city=row[2], state=row[3])
        for row in rows
    ]


def organization_can_estimate(property_ids: list[int]) -> bool:
    """Elegibilidade organizacional: existe telemetria real (com tarifa já
    calculada) para pelo menos uma das propriedades.

    Substitui fn_user_can_estimate para este caminho sem alterar a função do
    banco (fora de escopo mudar schema do delta-database): cost_value só é
    gravado em gold.ft_consumption_daily quando o ETL já calculou uma tarifa
    válida via fn_get_current_region_rate, então a mera existência da linha já
    implica telemetria + tarifa válidas — o mesmo papel que tb_device.is_active
    + tb_region_rate cumprem no caminho residencial.
    """
    if not property_ids:
        return False
    with _cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1
                  FROM gold.ft_consumption_daily f
                  JOIN gold.dm_property dp ON dp.property_key = f.property_key
                 WHERE dp.property_id = ANY(%s)
            );
            """,
            (property_ids,),
        )
        row = cur.fetchone()
    return bool(row[0]) if row is not None else False


def get_organization_consumption_history(
    property_ids: list[int], days: int, today: date
) -> list[ConsumptionPoint]:
    """Histórico diário (litros) somado por dia entre as propriedades
    informadas, lido de dw.vw_ft_consumption_daily. Cada dia vira um
    ConsumptionPoint sintético (janela de meia-noite a meia-noite) — formato
    aceito sem nenhuma mudança por app/tools/forecast/calculations.py, que só
    usa window_started_at e consumption_liters. user_id fica como placeholder
    0 porque o ponto representa a organização, não um único residente.
    """
    if not property_ids:
        return []
    with _cursor() as cur:
        cur.execute(
            """
            SELECT full_date, SUM(total_liters)
              FROM dw.vw_ft_consumption_daily
             WHERE property_id = ANY(%s)
               AND full_date BETWEEN %s AND %s
             GROUP BY full_date
             ORDER BY full_date;
            """,
            (property_ids, today - timedelta(days=days), today),
        )
        rows = cur.fetchall()
    points = []
    for full_date, total_liters in rows:
        start = datetime(full_date.year, full_date.month, full_date.day)
        points.append(
            ConsumptionPoint(
                user_id=0,
                window_started_at=start,
                window_finished_at=start + timedelta(days=1),
                consumption_liters=float(total_liters),
                anomaly_detected=False,
                device_id=None,
            )
        )
    return points


def get_organization_consumption_daily(
    property_ids: list[int], start_date: date, end_date: date
) -> list[tuple[date, Decimal]]:
    """Lê os registros diários das unidades autorizadas no intervalo de datas.

    A view tem granularidade diária. Os limites são datas inclusivas locais;
    a função não cria horários nem soma linhas antes de validar cada valor.
    """
    if not property_ids:
        return []
    if (
        not isinstance(start_date, date)
        or isinstance(start_date, datetime)
        or not isinstance(end_date, date)
        or isinstance(end_date, datetime)
    ):
        raise ValueError("O período diário precisa usar datas sem horário.")
    if start_date > end_date:
        raise ValueError("A data inicial é posterior à data final.")

    with _cursor() as cur:
        cur.execute(
            """
            SELECT full_date, total_liters
              FROM dw.vw_ft_consumption_daily
             WHERE property_id = ANY(%s)
               AND full_date BETWEEN %s AND %s
             ORDER BY full_date, property_id;
            """,
            (property_ids, start_date, end_date),
        )
        rows = cur.fetchall()
    return [(row[0], row[1]) for row in rows]


def get_organization_last_billed_period(
    property_ids: list[int], today: date
) -> LastWaterBill | None:
    """Equivalente organizacional de tb_last_water_bill (que não existe para
    organização): soma total_liters/cost_value do último mês calendário
    fechado. Como hoje só um punhado de propriedades têm telemetria real e
    podem não ter um mês inteiro fechado, cai no fallback de somar só o mês
    calendário da leitura mais recente disponível — evita retornar None
    sempre que o dado real ainda for escasso, sem misturar meses diferentes
    numa única "conta".
    """
    if not property_ids:
        return None
    with _cursor() as cur:
        month_end = today.replace(day=1) - timedelta(days=1)
        month_start = month_end.replace(day=1)

        cur.execute(
            """
            SELECT SUM(total_liters), SUM(cost_value)
              FROM dw.vw_ft_consumption_daily
             WHERE property_id = ANY(%s)
               AND full_date BETWEEN %s AND %s;
            """,
            (property_ids, month_start, month_end),
        )
        liters, cost = cur.fetchone()
        reference_month = month_start

        if liters is None:
            cur.execute(
                """
                WITH last_month AS (
                    SELECT DATE_TRUNC('month', MAX(full_date))::DATE AS m
                      FROM dw.vw_ft_consumption_daily
                     WHERE property_id = ANY(%s)
                )
                SELECT SUM(v.total_liters), SUM(v.cost_value), MAX(lm.m)
                  FROM dw.vw_ft_consumption_daily v
                  JOIN last_month lm ON DATE_TRUNC('month', v.full_date)::DATE = lm.m
                 WHERE v.property_id = ANY(%s);
                """,
                (property_ids, property_ids),
            )
            liters, cost, reference_month = cur.fetchone()
            if liters is None:
                return None
    return LastWaterBill(
        user_id=0,
        month=reference_month,
        total_value=Decimal(str(cost)).quantize(Decimal("0.01")),
        m3_value=(Decimal(str(liters)) / Decimal(1000)).quantize(Decimal("0.01")),
    )


def get_organization_effective_rate(
    property_ids: list[int], today: date, window_days: int = 30
) -> Decimal | None:
    """Tarifa efetiva (R$/m³) observada nos últimos window_days dias:
    SUM(cost_value) / (SUM(total_liters)/1000).

    Substitui fn_get_current_region_rate no caminho organizacional: as
    propriedades de uma organização podem estar em regiões/categorias
    diferentes, então não há um único region_id/classification_id válido para
    o conjunto — a razão custo/consumo já registrada pelo ETL evita duplicar
    essa lógica de tarifa por região aqui.
    """
    if not property_ids:
        return None
    with _cursor() as cur:
        cur.execute(
            """
            SELECT SUM(total_liters), SUM(cost_value)
              FROM dw.vw_ft_consumption_daily
             WHERE property_id = ANY(%s)
               AND full_date BETWEEN %s AND %s;
            """,
            (property_ids, today - timedelta(days=window_days), today),
        )
        liters, cost = cur.fetchone()
    if not liters:
        return None
    return (Decimal(str(cost)) / (Decimal(str(liters)) / Decimal(1000))).quantize(Decimal("0.01"))
