"""Cálculos determinísticos da simulação "e se" (sem LLM)."""

from __future__ import annotations

from dataclasses import dataclass

MAX_SIMULATION_DAYS = 366


@dataclass(frozen=True)
class ConsumptionScenario:
    """Cenário base e hipotético para um período, em litros."""

    change_pct: float
    days: int
    base_daily_liters: float
    scenario_daily_liters: float
    base_period_liters: float
    scenario_period_liters: float
    difference_liters: float


def simulate_percentage_change(
    baseline_daily_liters: float, change_pct: float, days: int
) -> ConsumptionScenario:
    """Aplica uma variação percentual ao consumo diário e compara com o cenário base.

    `change_pct` negativo reduz o consumo (ex.: -10) e positivo aumenta. A diferença é
    cenário menos base: negativa quando há economia.
    """
    if baseline_daily_liters <= 0:
        raise ValueError("O consumo diário de referência deve ser maior que zero.")
    if change_pct <= -100:
        raise ValueError("A redução deve ser menor que 100%.")
    if not 1 <= days <= MAX_SIMULATION_DAYS:
        raise ValueError(f"O período deve ter entre 1 e {MAX_SIMULATION_DAYS} dias.")

    scenario_daily = baseline_daily_liters * (1 + change_pct / 100)
    base_period = baseline_daily_liters * days
    scenario_period = scenario_daily * days
    return ConsumptionScenario(
        change_pct=change_pct,
        days=days,
        base_daily_liters=round(baseline_daily_liters, 1),
        scenario_daily_liters=round(scenario_daily, 1),
        base_period_liters=round(base_period, 1),
        scenario_period_liters=round(scenario_period, 1),
        difference_liters=round(scenario_period - base_period, 1),
    )
