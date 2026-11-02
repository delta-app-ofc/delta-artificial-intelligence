"""Cálculos determinísticos do custo da água de um hábito (sem LLM)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

WEEKS_PER_MONTH = Decimal("4.33")

# Litros por ocorrência (médias de referência, não medições do hidrômetro).
LITERS_PER_SESSION: dict[str, float] = {
    "BANHO LONGO": 80.0,
    "LAVAR QUINTAL": 150.0,
    "LAVAR ROUPA": 100.0,
    "REGAR PLANTAS": 15.0,
    "LAVAR CARRO": 200.0,
    "LAVAR LOUÇA": 20.0,
}
_LITERS_PER_M3 = Decimal("1000")


@dataclass(frozen=True)
class HabitCost:
    """Projeção de litros e custo estimado da água de um hábito."""

    liters_per_week: Decimal
    liters_per_month: Decimal
    m3_per_month: Decimal
    cost_per_month: Decimal


def summarize_habit_baseline(habits: list[dict]) -> dict:
    """Soma os litros esperados dos hábitos cadastrados, por hábito, por dia e no mês.

    Cada ocorrência usa `estimated_liters` do cadastro quando existe e, senão, a média de
    referência do catálogo. Hábito fora do catálogo e sem litros informados é ignorado.
    """
    items: list[dict] = []
    by_day: dict[str, float] = {}
    for habit in habits:
        reference = LITERS_PER_SESSION.get(habit["name"])
        liters = habit.get("estimated_liters")
        source = "cadastro" if liters is not None else "referência"
        liters = liters if liters is not None else reference
        if liters is None:
            continue
        per_week = float(liters) * habit["frequency"]
        items.append({
            "name": habit["name"],
            "frequency_per_week": habit["frequency"],
            "liters_per_session": liters,
            "liters_source": source,
            "liters_per_week": round(per_week, 1),
            "days": habit.get("days", []),
        })
        for day in habit.get("days", []):
            by_day[day] = round(by_day.get(day, 0.0) + float(liters), 1)
    week_total = round(sum(item["liters_per_week"] for item in items), 1)
    return {
        "habits": items,
        "liters_per_day_of_week": by_day,
        "liters_per_week": week_total,
        "liters_per_month": round(week_total * float(WEEKS_PER_MONTH), 1),
    }


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
