"""Todas as exceções do projeto, num lugar só (em vez de espalhadas em cada
arquivo de tool). Conforme o projeto crescer, novas exceções entram aqui.
"""


class RegionRateNotFound(RuntimeError):
    """Não existe tarifa vigente para a região e a data consultadas."""


class ForecastUnavailableError(RuntimeError):
    """O usuário não está apto a receber estimativas (fn_user_can_estimate = false)."""
