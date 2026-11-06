"""Extrai consumo do texto original e converte litros em m³ sem usar o LLM."""
import re
from decimal import Decimal

_VOLUME = re.compile(
    r"(?<![\w.,+-])([+-]?\d+(?:[.,]\d+)*)\s*(cm[³3]|mm[³3]|ml|mililitros?|centímetros?\s+cúbicos?|galões?|galão|gallons?|ft[³3]|pés?\s+cúbicos?|m[³3]|metros?\s+cúbicos?|litros?|l)(?!\w)",
    re.I,
)
_NUMBER = re.compile(r"(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?")
_NEGATED_VOLUME = re.compile(r"(?<!\w)(?:não|nao)\s*$", re.I)
MESSAGE = (
    "Informe um único consumo em m³ ou litros, com unidade explícita e vírgula para decimais. "
    "Outras unidades precisam ser esclarecidas antes do cadastro."
)

def consumption_from_message(message: str | None) -> tuple[float, str]:
    """Recusa unidade ausente, não suportada ou consumos divergentes."""
    matches = list(_VOLUME.finditer(message or ""))
    if not matches:
        raise ValueError(MESSAGE)
    values = []
    affirmed = []
    for match in matches:
        prefix = (message or "")[:match.start()]
        # Em "1.200 litros (não 1.200 m³)", o segundo volume foi excluído
        # explicitamente. Só reconhecemos a negação imediatamente antes do número.
        if _NEGATED_VOLUME.search(prefix):
            continue
        number, unit = match.group(1), match.group(2).lower()
        # Não interprete só o final de números fragmentados como "1 200 L" ou "1/2 m³".
        if re.search(r"\d[\s.,/]+$", (message or "")[:match.start()]):
            raise ValueError(MESSAGE)
        if len(number) > 20 or not _NUMBER.fullmatch(number):
            raise ValueError(MESSAGE)
        value = Decimal(number.replace(".", "").replace(",", "."))
        if unit in {"l", "litro", "litros"}:
            value /= 1000
        elif unit not in {"m³", "m3", "metro cúbico", "metros cúbicos"}:
            raise ValueError(MESSAGE)
        if value != value.quantize(Decimal("0.01")):
            raise ValueError("O consumo precisa ser representável com duas casas decimais em m³. Confira o valor da fatura.")
        values.append(value)
        affirmed.append(match)
    if len(set(values)) != 1:
        raise ValueError(MESSAGE)
    return float(values[0]), " / ".join(match.group(0) for match in affirmed)
