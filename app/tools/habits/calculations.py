"""Cálculos determinísticos do custo da água de um hábito (sem LLM)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

WEEKS_PER_MONTH = Decimal("4.33")
_LITERS_PER_M3 = Decimal("1000")


@dataclass(frozen=True)
class HabitCost:
    """Projeção de litros e custo estimado da água de um hábito."""

    liters_per_week: Decimal
    liters_per_month: Decimal
    m3_per_month: Decimal
    cost_per_month: Decimal


def estimate_habit_cost(
    liters_per_session: float | Decimal,
    frequency_per_week: int,
    rate_per_m3: float | Decimal,
) -> HabitCost:
    """Projeta litros por semana e por mês e o custo mensal da água do hábito.

    O mês tem 4,33 semanas, a mesma convenção da estimativa de litros. Só o valor
    em reais é arredondado (2 casas, meia para cima); a tarifa é a de água por m³.
    """
    liters = Decimal(str(liters_per_session))
    rate = Decimal(str(rate_per_m3))
    if liters <= 0 or frequency_per_week < 1 or rate < 0:
        raise ValueError("Litros e frequência devem ser positivos e a tarifa não pode ser negativa.")

    liters_per_week = liters * frequency_per_week
    liters_per_month = liters_per_week * WEEKS_PER_MONTH
    m3_per_month = liters_per_month / _LITERS_PER_M3
    cost = (m3_per_month * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return HabitCost(
        liters_per_week=liters_per_week,
        liters_per_month=liters_per_month,
        m3_per_month=m3_per_month,
        cost_per_month=cost,
    )
