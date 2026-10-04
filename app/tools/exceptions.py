class DatabaseAccessError(RuntimeError):
    """Erro de acesso a banco com mensagem pública segura."""


class DatabaseConnectionError(DatabaseAccessError):
    """Não foi possível estabelecer conexão com um banco de dados."""


class DatabaseQueryError(DatabaseAccessError):
    """Não foi possível executar uma consulta em um banco de dados."""

    def __init__(self, message: str, *, code: str | int | None = None) -> None:
        super().__init__(message)
        # Código protocolar opcional, para decisões internas sem expor detalhes
        # do driver na mensagem enviada ao agente.
        self.code = code


class RegionRateNotFound(RuntimeError):
    """Não existe tarifa vigente para a região e a data consultadas."""


class ForecastUnavailableError(RuntimeError):
    """O usuário não está apto a receber estimativas (fn_user_can_estimate = false)."""
