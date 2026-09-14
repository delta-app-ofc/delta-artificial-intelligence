"""
REGRAS DE DETECÇÃO — heurísticas explicáveis.

OBSERVAÇÃO / TRABALHO FUTURO — perfis não residenciais:
`overnight_rule` assume rotina "residencial" (baixo consumo 00h-05h). Isso NÃO
vale pra `tb_property.classification = 'COMERCIAL'` (ex.: comércio/indústria
com operação/turno noturno). Hoje o schema (delta-sql-database) não tem uma
tabela de horário de funcionamento por propriedade; quando/se existir,
`overnight_rule` deve: (1) consultar a classificação e os turnos cadastrados;
(2) só aplicar a janela "00h-05h suspeita" quando não houver operação noturna
conhecida; (3) pra comerciais/industriais, confiar na baseline estatística
(`extreme_deviation_rule`), que já se adapta ao padrão de cada propriedade.
Por ora, `overnight_rule` recebe a classificação e simplesmente não dispara
pra COMERCIAL.
"""

from __future__ import annotations

from detection.features import WindowFeatures

MIN_CONSECUTIVE_FLOW_WINDOWS = 6   # 6 janelas de 5 min = 30 min contínuos
MIN_OVERNIGHT_LITERS = 1.0         # litros na janela, de madrugada, já suspeito
# Z_THRESHOLD não é fixo aqui: é calibrado em train.py (ver calibrate_z_threshold)
# a partir da distribuição de baseline_deviation nos dados normais, e
# documentado no detection/README.md — nunca um número "chutado".


def continuous_flow_rule(features: WindowFeatures) -> bool:
    return features.consecutive_flow_windows >= MIN_CONSECUTIVE_FLOW_WINDOWS


def overnight_rule(features: WindowFeatures, property_classification: str | None) -> bool:
    if property_classification == "COMERCIAL":
        return False  # ver observação no topo do arquivo
    return bool(features.is_overnight) and features.consumption_liters > MIN_OVERNIGHT_LITERS


def extreme_deviation_rule(features: WindowFeatures, z_threshold: float) -> bool:
    return abs(features.baseline_deviation) >= z_threshold


def calibrate_z_threshold(normal_baseline_deviations: list[float], percentile: float = 99) -> float:
    """Escolhe Z_THRESHOLD como um percentil da distribuição de desvios vista
    em dados CONHECIDAMENTE NORMAIS — ex.: percentile=99 significa que só ~1%
    das janelas normais seriam (erradamente) marcadas. Isso É a calibração,
    não um chute."""
    values = sorted(abs(v) for v in normal_baseline_deviations)
    if not values:
        return 3.0  # fallback conservador se não houver dado pra calibrar
    index = min(int(len(values) * percentile / 100), len(values) - 1)
    return values[index]
