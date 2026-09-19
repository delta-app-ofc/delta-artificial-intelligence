class RegionRateNotFound(RuntimeError):
    """Não existe tarifa vigente para a região e a data consultadas."""


class ForecastUnavailableError(RuntimeError):
    """O usuário não está apto a receber estimativas (fn_user_can_estimate = false)."""
