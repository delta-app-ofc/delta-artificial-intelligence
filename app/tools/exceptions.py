from typing import Literal


_DATABASE_NAMES = {"PostgreSQL", "MongoDB"}


def _database_label(database: str) -> str:
    if database not in _DATABASE_NAMES:
        raise ValueError("database deve ser PostgreSQL ou MongoDB.")
    return database


class DatabaseAccessError(RuntimeError):
    """Erro de acesso a banco com mensagem pública segura."""


class DatabaseConnectionError(DatabaseAccessError):
    """Não foi possível estabelecer conexão com um banco de dados."""

    def __init__(self, database: Literal["PostgreSQL", "MongoDB"]) -> None:
        label = _database_label(database)
        super().__init__(f"Não foi possível conectar ao {label}.")


class DatabaseQueryError(DatabaseAccessError):
    """Não foi possível executar uma consulta em um banco de dados."""

    def __init__(
        self,
        database: Literal["PostgreSQL", "MongoDB"],
        *,
        code: str | int | None = None,
    ) -> None:
        label = _database_label(database)
        super().__init__(f"Não foi possível executar a consulta no {label}.")
        # Código protocolar opcional, para decisões internas sem expor detalhes
        # do driver na mensagem enviada ao agente.
        self.code = code


class DatabaseDataError(DatabaseQueryError):
    """Documento retornado pelo banco não corresponde ao contrato esperado."""


class RegionRateNotFound(RuntimeError):
    """Não existe tarifa vigente para a região e a data consultadas."""


class ForecastUnavailableError(RuntimeError):
    """O usuário não está apto a receber estimativas (fn_user_can_estimate = false)."""
