from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Iterator, Literal

import psycopg2
from psycopg2.pool import ThreadedConnectionPool

from app.config import get_settings, validate_postgres_config
from app.tools.exceptions import (
    DatabaseConnectionError,
    DatabaseQueryError,
    RegionRateNotFound,
)
from app.tools.models import ConsumptionPoint, LastWaterBill, OrganizationProperty

logger = logging.getLogger(__name__)


_pool: ThreadedConnectionPool | None = None
_pool_slots: threading.BoundedSemaphore | None = None
_pool_lock = threading.Lock()


def get_conn():
    """Conexão direta, fora do pool (útil só para diagnóstico; o acesso normal usa _cursor)."""
    settings = get_settings()
    validate_postgres_config(settings=settings)
    database_url = settings.database_url or ""

    try:
        return psycopg2.connect(
            database_url,
            connect_timeout=settings.db_connect_timeout_seconds,
        )
    except psycopg2.Error as exc:
        raise DatabaseConnectionError("PostgreSQL") from exc


def _get_pool() -> tuple[ThreadedConnectionPool, threading.BoundedSemaphore]:
    """Cria o pool no primeiro uso; o semáforo limita quantas operações usam o pool ao mesmo tempo."""
    global _pool, _pool_slots
    with _pool_lock:
        if _pool is None or _pool_slots is None:
            settings = get_settings()
            validate_postgres_config(settings=settings)
            try:
                _pool = ThreadedConnectionPool(
                    settings.db_pool_min_size,
                    settings.db_pool_max_size,
                    settings.database_url or "",
                    connect_timeout=settings.db_connect_timeout_seconds,
                )
            except psycopg2.Error as exc:
                raise DatabaseConnectionError("PostgreSQL") from exc
            # O psycopg2 só guarda "minconn" conexões ociosas e fecha as outras ao devolver;
            # depois de abrir as iniciais, sobe o limite para manter até o máximo e evitar reconexões.
            _pool.minconn = settings.db_pool_max_size
            _pool_slots = threading.BoundedSemaphore(settings.db_pool_max_size)
        return _pool, _pool_slots


def close_pool() -> None:
    """Fecha todas as conexões do pool; é seguro chamar mais de uma vez."""
    global _pool, _pool_slots
    with _pool_lock:
        pool, _pool, _pool_slots = _pool, None, None
    if pool is not None:
        try:
            pool.closeall()
        except Exception as exc:
            raise DatabaseConnectionError("PostgreSQL") from exc


def _discard(pool: ThreadedConnectionPool, conn) -> None:
    """Devolve ao pool fechando a conexão, sem deixar erro de limpeza escapar."""
    try:
        pool.putconn(conn, close=True)
    except Exception:
        try:
            conn.close()
        except Exception:
            pass


def _start_cursor(pool: ThreadedConnectionPool, holder: dict):
    """Prepara o cursor com o timeout da consulta; troca uma vez uma conexão quebrada do pool.

    Só roda antes do SQL da operação, então refazer a tentativa nunca repete uma escrita.
    """
    timeout_ms = f"{get_settings().db_query_timeout_seconds * 1000}ms"
    for attempt in (1, 2):
        conn = holder["conn"]
        cur = None
        try:
            if conn.closed:
                raise psycopg2.InterfaceError("conexão fechada")
            cur = conn.cursor()
            # set_config local expira ao fim da transação: não vaza entre usos do pool.
            cur.execute("SELECT set_config('statement_timeout', %s, true);", (timeout_ms,))
            return cur
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as exc:
            if cur is not None:
                try:
                    cur.close()
                except Exception:
                    pass
            _discard(pool, conn)
            holder["conn"] = None
            if attempt == 2:
                raise DatabaseConnectionError("PostgreSQL") from exc
            try:
                holder["conn"] = pool.getconn()
            except psycopg2.Error as new_exc:
                raise DatabaseConnectionError("PostgreSQL") from new_exc


@contextmanager
def _cursor() -> Iterator:
    """Empresta uma conexão do pool, entrega um cursor e devolve a conexão, protegendo mensagens do driver."""
    pool, slots = _get_pool()
    wait_seconds = get_settings().db_pool_wait_seconds
    if not slots.acquire(timeout=wait_seconds):
        raise DatabaseConnectionError("PostgreSQL")

    holder: dict = {"conn": None}
    cur = None
    operation_failed = False
    try:
        try:
            holder["conn"] = pool.getconn()
        except psycopg2.Error as exc:
            raise DatabaseConnectionError("PostgreSQL") from exc
        cur = _start_cursor(pool, holder)
        yield cur
        holder["conn"].commit()
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
        conn = holder["conn"]
        try:
            if conn is not None:
                if conn.closed:
                    # Conexão fechada ou quebrada: sai do pool. Erro de consulta (inclusive timeout)
                    # com a conexão saudável não descarta nada.
                    _discard(pool, conn)
                else:
                    # putconn desfaz transação aberta, então uma falha nunca contamina o próximo uso.
                    pool.putconn(conn)
        except Exception as exc:
            if cleanup_error is None:
                cleanup_error = exc
        finally:
            slots.release()

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


def is_user_active(user_id: int) -> bool:
    """True só se o usuário existe e está ativo (tb_user.is_active), a mesma regra do back-end.

    Uma consulta indexada pela chave primária, na conexão que já está no pool.
    """
    try:
        with _cursor() as cur:
            cur.execute("SELECT fn_user_is_active(%s);", (user_id,))
            row = cur.fetchone()
    except DatabaseQueryError as exc:
        # fn_user_is_active levanta uma exceção (P0001) quando o usuário não existe.
        if exc.code == "P0001":
            return False
        raise
    return bool(row and row[0])


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


def organization_can_estimate(user_id: int, property_ids: list[int]) -> bool:
    """Elegibilidade organizacional: existe telemetria real (com tarifa já
    calculada) para pelo menos uma das propriedades do usuário. O banco
    descarta ids de outras organizações (fn_user_authorized_property_ids).

    Usa fn_organization_can_estimate do banco, equivalente organizacional de
    fn_user_can_estimate.
    """
    if not property_ids:
        return False
    with _cursor() as cur:
        cur.execute("SELECT fn_organization_can_estimate(%s, %s);", (user_id, property_ids))
        row = cur.fetchone()
    return bool(row[0]) if row is not None else False


def get_organization_consumption_history(
    user_id: int, property_ids: list[int], days: int, today: date
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
            "SELECT full_date, total_liters FROM fn_organization_consumption_history(%s, %s, %s, %s);",
            (user_id, property_ids, days, today),
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
    user_id: int, property_ids: list[int], start_date: date, end_date: date
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
             WHERE property_id IN (SELECT UNNEST(fn_user_authorized_property_ids(%s, %s)))
               AND full_date BETWEEN %s AND %s
             ORDER BY full_date, property_id;
            """,
            (user_id, property_ids, start_date, end_date),
        )
        rows = cur.fetchall()
    return [(row[0], row[1]) for row in rows]


def get_organization_last_billed_period(
    user_id: int, property_ids: list[int], today: date
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
              FROM fn_organization_last_billed_period(%s, %s, %s);
            """,
            (user_id, property_ids, today),
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
            # A mensagem do banco pode trazer detalhes internos: vai só para o log.
            logger.warning("Cadastro de hábito recusado pelo banco: %s", exc.diag.message_primary)
            raise ValueError(
                "Não foi possível cadastrar o hábito. Ele pode já estar cadastrado "
                "ou os dados informados são inválidos."
            ) from exc
    return {"name": name, "frequency": frequency, "days": days}


def get_investment_scenarios(user_id: int) -> list[dict]:
    """Cenários de investimento do catálogo (sem organização) e os das organizações do usuário.

    Cada item tem: name, investment_value, reduction_pct, annual_savings_value, payback_months
    (pode ser None) e description (pode ser None); valores numéricos como float.
    """
    with _cursor() as cur:
        cur.execute(
            """
            SELECT s.name, s.investment_value, s.reduction_pct, s.annual_savings_value,
                   s.payback_months, s.description
              FROM tb_investment_scenario s
             WHERE s.organization_id IS NULL
                OR s.organization_id IN (
                       SELECT organization_id FROM tb_user_organization WHERE user_id = %s
                   )
             ORDER BY s.payback_months NULLS LAST, s.name;
            """,
            (user_id,),
        )
        rows = cur.fetchall()
    return [
        {
            "name": name,
            "investment_value": float(value),
            "reduction_pct": float(reduction),
            "annual_savings_value": float(savings),
            "payback_months": float(payback) if payback is not None else None,
            "description": description,
        }
        for name, value, reduction, savings, payback, description in rows
    ]


def get_organization_effective_rate(
    user_id: int, property_ids: list[int], today: date, window_days: int = 30
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
            "SELECT fn_organization_effective_rate(%s, %s, %s, %s);",
            (user_id, property_ids, today, window_days),
        )
        row = cur.fetchone()
    if row is None or row[0] is None:
        return None
    return Decimal(str(row[0])).quantize(Decimal("0.01"))
