from __future__ import annotations

from datetime import date
from decimal import Decimal

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
from app.tools.models import LastWaterBill


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


def get_current_region_rate(region_id: int, on_date: date) -> Decimal:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT fn_get_current_region_rate(%s, %s);", (region_id, on_date))
        row = cur.fetchone()
        if row is None or row[0] is None:
            raise RegionRateNotFound(
                f"Sem tarifa vigente para a região {region_id} em {on_date}."
            )
        return Decimal(str(row[0]))
    except psycopg2.errors.RaiseException as exc:  # type: ignore[attr-defined]
        raise RegionRateNotFound(
            f"Sem tarifa vigente para a região {region_id} em {on_date}."
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
