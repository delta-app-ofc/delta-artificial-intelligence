from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Iterator, Literal

import psycopg2
from psycopg2.extensions import parse_dsn

from app.config import get_settings, validate_postgres_config
from app.tools.exceptions import (
    DatabaseConnectionError,
    DatabaseQueryError,
    RegionRateNotFound,
)
from app.tools.models import ConsumptionPoint, LastWaterBill, OrganizationProperty


def get_conn():
    settings = get_settings()
    validate_postgres_config(settings=settings)
    database_url = settings.database_url or ""
    query_timeout_ms = settings.db_query_timeout_seconds * 1000
    statement_timeout_option = f"-c statement_timeout={query_timeout_ms}ms"

    try:
        existing_options = parse_dsn(database_url).get("options", "")
        options = " ".join(
            value for value in (existing_options, statement_timeout_option) if value
        )
        return psycopg2.connect(
            database_url,
            connect_timeout=settings.db_connect_timeout_seconds,
            options=options,
        )
    except psycopg2.Error as exc:
        raise DatabaseConnectionError("PostgreSQL") from exc


@contextmanager
def _cursor() -> Iterator:
    """Abre e fecha cursor/conexão, protegendo mensagens do driver."""
    conn = get_conn()
    cur = None
    operation_failed = False
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    except psycopg2.Error as exc:
        operation_failed = True
        raise DatabaseQueryError(
            "PostgreSQL",
            code=getattr(exc, "pgcode", None),
        ) from exc
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
            if isinstance(cleanup_error, psycopg2.Error):
                raise DatabaseQueryError(
                    "PostgreSQL",
                    code=getattr(cleanup_error, "pgcode", None),
                ) from cleanup_error
            raise DatabaseQueryError("PostgreSQL") from cleanup_error


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
        cur.execute("SELECT region_id FROM fn_get_user_property_context(%s);", (user_id,))
        row = cur.fetchone()
    return int(row[0]) if row is not None and row[0] is not None else None


def get_user_property_classification_id(user_id: int) -> int | None:
    with _cursor() as cur:
        cur.execute(
            "SELECT classification_id FROM fn_get_user_property_context(%s);", (user_id,)
        )
        row = cur.fetchone()
    return int(row[0]) if row is not None and row[0] is not None else None


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

    Usa fn_user_access_kind do banco: vínculo residencial tem prioridade sobre
    o organizacional.
    """
    with _cursor() as cur:
        cur.execute("SELECT fn_user_access_kind(%s);", (user_id,))
        row = cur.fetchone()
    if row is None or row[0] not in ("residential", "organizational"):
        return "none"
    return row[0]


def get_user_organization_properties(user_id: int) -> list[OrganizationProperty]:
    """Todas as propriedades de todas as organizações vinculadas ao usuário
    (tb_user_organization é M:N; não há papel/hierarquia, então todas as
    organizações do usuário entram no mesmo conjunto agregável)."""
    with _cursor() as cur:
        cur.execute(
            """
            SELECT property_id, name, city, state
              FROM fn_user_organization_properties(%s)
             ORDER BY property_id;
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

    Usa fn_organization_can_estimate do banco, equivalente organizacional de
    fn_user_can_estimate.
    """
    if not property_ids:
        return False
    with _cursor() as cur:
        cur.execute("SELECT fn_organization_can_estimate(%s);", (property_ids,))
        row = cur.fetchone()
    return bool(row[0]) if row is not None else False


def get_organization_consumption_history(
    property_ids: list[int], days: int, today: date
) -> list[ConsumptionPoint]:
    """Histórico diário (litros) somado por dia entre as propriedades
    informadas, via fn_organization_consumption_history (janela de `days`
    dias terminando em `today`). Cada dia vira um
    ConsumptionPoint sintético (janela de meia-noite a meia-noite) — formato
    aceito sem nenhuma mudança por app/tools/forecast/calculations.py, que só
    usa window_started_at e consumption_liters. user_id fica como placeholder
    0 porque o ponto representa a organização, não um único residente.
    """
    if not property_ids:
        return []
    with _cursor() as cur:
        cur.execute(
            "SELECT full_date, total_liters FROM fn_organization_consumption_history(%s, %s, %s);",
            (property_ids, days, today),
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
    organização) via fn_organization_last_billed_period: soma do último mês
    fechado, com fallback para o mês da leitura mais recente quando não há
    mês fechado com dados.
    """
    if not property_ids:
        return None
    with _cursor() as cur:
        cur.execute(
            """
            SELECT reference_month, total_liters, total_cost
              FROM fn_organization_last_billed_period(%s, %s);
            """,
            (property_ids, today),
        )
        row = cur.fetchone()
    if row is None or row[1] is None:
        return None
    reference_month, liters, cost = row
    return LastWaterBill(
        user_id=0,
        month=reference_month,
        total_value=Decimal(str(cost)).quantize(Decimal("0.01")),
        m3_value=(Decimal(str(liters)) / Decimal(1000)).quantize(Decimal("0.01")),
    )


def get_user_habits(user_id: int) -> list[dict]:
    """Retorna os hábitos de consumo de água do usuário.

    Cada item tem: name (str), category (str), frequency (int — vezes por
    semana), days (list[str] — dias em maiúsculas, ex.: SEGUNDA), start_time e
    end_time (str HH:MM ou None) e estimated_liters (float ou None).
    """
    with _cursor() as cur:
        cur.execute(
            """
            SELECT name, category, frequency, days,
                   to_char(start_time, 'HH24:MI'),
                   to_char(end_time, 'HH24:MI'),
                   estimated_liters
              FROM fn_user_habits(%s);
            """,
            (user_id,),
        )
        rows = cur.fetchall()
    return [
        {
            "name": name,
            "category": category,
            "frequency": freq,
            "days": list(days),
            "start_time": start,
            "end_time": end,
            "estimated_liters": float(liters) if liters is not None else None,
        }
        for name, category, freq, days, start, end, liters in rows
    ]


def get_habits_by_weekday(user_id: int, day: str) -> list[dict]:
    """Retorna os hábitos do usuário que ocorrem no dia da semana informado.

    `day` deve estar em maiúsculas (ex.: SEGUNDA, SABADO).
    Cada item retornado tem: name, frequency, start_time, end_time (HH:MM ou
    None) e estimated_liters (float ou None).
    """
    with _cursor() as cur:
        cur.execute(
            """
            SELECT name, frequency,
                   to_char(start_time, 'HH24:MI'),
                   to_char(end_time, 'HH24:MI'),
                   estimated_liters
              FROM fn_user_habits_by_day(%s, %s);
            """,
            (user_id, day),
        )
        rows = cur.fetchall()
    return [
        {
            "name": name,
            "frequency": freq,
            "start_time": start,
            "end_time": end,
            "estimated_liters": float(liters) if liters is not None else None,
        }
        for name, freq, start, end, liters in rows
    ]


def get_user_location(user_id: int) -> dict | None:
    """Retorna cidade, estado e país do primeiro imóvel vinculado ao usuário.

    Retorna None quando o usuário não tem imóvel cadastrado.
    """
    with _cursor() as cur:
        cur.execute("SELECT city, state FROM fn_user_location(%s);", (user_id,))
        row = cur.fetchone()
    if row is None:
        return None
    return {"city": row[0], "state": row[1], "country": "BR"}


def create_habit(user_id: int, name: str, frequency: int, days: list[str]) -> dict:
    """Cadastra um hábito e vincula os dias da semana.

    Retorna confirmação com name, frequency e days.
    Levanta ValueError se o hábito já existir ou os dados forem inválidos.
    """
    with _cursor() as cur:
        try:
            cur.execute(
                "SELECT fn_create_user_habit(%s, %s, %s, %s);",
                (user_id, name, frequency, days),
            )
        except psycopg2.errors.RaiseException as exc:  # type: ignore[attr-defined]
            raise ValueError(exc.diag.message_primary) from exc
    return {"name": name, "frequency": frequency, "days": days}


def get_organization_effective_rate(
    property_ids: list[int], today: date, window_days: int = 30
) -> Decimal | None:
    """Tarifa efetiva (R$/m³) observada nos últimos window_days dias, via
    fn_organization_effective_rate. Retorna None sem consumo na janela.

    Substitui fn_get_current_region_rate no caminho organizacional: as
    propriedades podem estar em regiões/categorias diferentes, então usa-se a
    razão custo/consumo já registrada pelo ETL.
    """
    if not property_ids:
        return None
    with _cursor() as cur:
        cur.execute(
            "SELECT fn_organization_effective_rate(%s, %s, %s);",
            (property_ids, today, window_days),
        )
        row = cur.fetchone()
    if row is None or row[0] is None:
        return None
    return Decimal(str(row[0])).quantize(Decimal("0.01"))
