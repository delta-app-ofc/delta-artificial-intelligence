from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal

import psycopg2

from app.config import (
    DATABASE_URL,
    HOST_DB,
    NAME_DB,
    PASSWORD_DB,
    PORT_DB,
    USER_DB,
)
from app.tools.exceptions import RegionRateNotFound
from app.tools.models import ConsumptionPoint, LastWaterBill, OrganizationProperty


def get_conn():
    if all((HOST_DB, PORT_DB, USER_DB, PASSWORD_DB, NAME_DB)):
        return psycopg2.connect(
            host=HOST_DB,
            port=PORT_DB,
            user=USER_DB,
            password=PASSWORD_DB,
            dbname=NAME_DB,
        )
    return psycopg2.connect(DATABASE_URL)


def user_can_estimate(user_id: int) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT fn_user_can_estimate(%s);", (user_id,))
        row = cur.fetchone()
        return bool(row[0]) if row is not None else False
    finally:
        cur.close()
        conn.close()


def get_user_region_id(user_id: int) -> int | None:
    conn = get_conn()
    cur = conn.cursor()
    try:
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
    finally:
        cur.close()
        conn.close()


def get_user_property_classification_id(user_id: int) -> int | None:
    conn = get_conn()
    cur = conn.cursor()
    try:
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
    finally:
        cur.close()
        conn.close()


def get_current_region_rate(region_id: int, classification_id: int, on_date: date) -> Decimal:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT fn_get_current_region_rate(%s, %s, %s);",
            (region_id, classification_id, on_date),
        )
        row = cur.fetchone()
        if row is None or row[0] is None:
            raise RegionRateNotFound(
                f"Sem tarifa vigente para a região {region_id}, categoria {classification_id} em {on_date}."
            )
        return Decimal(str(row[0]))
    except psycopg2.errors.RaiseException as exc:  # type: ignore[attr-defined]
        raise RegionRateNotFound(
            f"Sem tarifa vigente para a região {region_id}, categoria {classification_id} em {on_date}."
        ) from exc
    finally:
        cur.close()
        conn.close()


def get_last_water_bill(user_id: int) -> LastWaterBill | None:
    conn = get_conn()
    cur = conn.cursor()
    try:
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
    finally:
        cur.close()
        conn.close()


def get_user_access_kind(user_id: int) -> Literal["residential", "organizational", "none"]:
    """Resolve como o usuário se relaciona com propriedades.

    Prioridade: se o usuário tem qualquer linha em tb_user_property, é tratado
    como residencial (caminho antigo, inalterado). Só verifica
    tb_user_organization quando não há nenhuma propriedade residencial.
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT 1 FROM tb_user_property WHERE user_id = %s LIMIT 1;", (user_id,))
        if cur.fetchone() is not None:
            return "residential"
        cur.execute("SELECT 1 FROM tb_user_organization WHERE user_id = %s LIMIT 1;", (user_id,))
        if cur.fetchone() is not None:
            return "organizational"
        return "none"
    finally:
        cur.close()
        conn.close()


def get_user_organization_properties(user_id: int) -> list[OrganizationProperty]:
    """Todas as propriedades de todas as organizações vinculadas ao usuário
    (tb_user_organization é M:N; não há papel/hierarquia, então todas as
    organizações do usuário entram no mesmo conjunto agregável)."""
    conn = get_conn()
    cur = conn.cursor()
    try:
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
        return [
            OrganizationProperty(property_id=row[0], name=row[1], city=row[2], state=row[3])
            for row in cur.fetchall()
        ]
    finally:
        cur.close()
        conn.close()


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
    conn = get_conn()
    cur = conn.cursor()
    try:
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
    finally:
        cur.close()
        conn.close()


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
    conn = get_conn()
    cur = conn.cursor()
    try:
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
        points = []
        for full_date, total_liters in cur.fetchall():
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
    finally:
        cur.close()
        conn.close()


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
    conn = get_conn()
    cur = conn.cursor()
    try:
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
    finally:
        cur.close()
        conn.close()


def get_user_habits(user_id: int) -> list[dict]:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT h.name, uh.frequency,
                   array_agg(dw.name ORDER BY dw.id)
                     FILTER (WHERE dw.name IS NOT NULL) AS days
              FROM tb_user_habit uh
              JOIN tb_habit h ON h.id = uh.habit_id
              LEFT JOIN tb_user_habit_day uhd ON uhd.user_habit_id = uh.id
              LEFT JOIN tb_day_of_week dw ON dw.id = uhd.day_of_week_id
             WHERE uh.user_id = %s
             GROUP BY h.name, uh.frequency
             ORDER BY h.name;
            """,
            (user_id,),
        )
        return [
            {"name": row[0], "frequency": row[1], "days": row[2] or []}
            for row in cur.fetchall()
        ]
    finally:
        cur.close()
        conn.close()


def create_habit(
    user_id: int, habit_name: str, frequency: int, days: list[str]
) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM tb_habit WHERE name = %s;", (habit_name,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"Hábito '{habit_name}' não existe no catálogo.")
        habit_id = int(row[0])

        cur.execute(
            """
            INSERT INTO tb_user_habit (user_id, habit_id, frequency)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, habit_id)
            DO UPDATE SET frequency = EXCLUDED.frequency
            RETURNING id;
            """,
            (user_id, habit_id, frequency),
        )
        user_habit_id = int(cur.fetchone()[0])

        linked_days: list[str] = []
        for day_name in days:
            cur.execute(
                "SELECT id FROM tb_day_of_week WHERE name = %s;", (day_name,)
            )
            day_row = cur.fetchone()
            if day_row is None:
                raise ValueError(f"Dia '{day_name}' não existe no banco.")
            cur.execute(
                """
                INSERT INTO tb_user_habit_day (user_habit_id, day_of_week_id)
                VALUES (%s, %s)
                ON CONFLICT (user_habit_id, day_of_week_id) DO NOTHING;
                """,
                (user_habit_id, int(day_row[0])),
            )
            linked_days.append(day_name)

        conn.commit()
        return {
            "user_habit_id": user_habit_id,
            "habit_name": habit_name,
            "frequency": frequency,
            "days": linked_days,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def get_habits_by_weekday(user_id: int, day: str) -> list[dict]:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT h.name, uh.frequency
              FROM tb_user_habit uh
              JOIN tb_habit h ON h.id = uh.habit_id
              JOIN tb_user_habit_day uhd ON uhd.user_habit_id = uh.id
              JOIN tb_day_of_week dw ON dw.id = uhd.day_of_week_id
             WHERE uh.user_id = %s AND dw.name = %s;
            """,
            (user_id, day),
        )
        return [{"name": row[0], "frequency": row[1]} for row in cur.fetchall()]
    finally:
        cur.close()
        conn.close()


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
    conn = get_conn()
    cur = conn.cursor()
    try:
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
    finally:
        cur.close()
        conn.close()
