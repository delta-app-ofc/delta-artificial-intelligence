class RegionRateNotFound(RuntimeError):
    """Não existe tarifa vigente para a região e a data consultadas."""


class ForecastUnavailableError(RuntimeError):
    """O usuário não está apto a receber estimativas (fn_user_can_estimate = false)."""


_KNOWN_DATABASES = {"PostgreSQL", "MongoDB"}


class DatabaseAccessError(RuntimeError):
    """Falha genérica de acesso ao banco — base para erros mais específicos."""


class DatabaseConnectionError(DatabaseAccessError):
    """Falha ao conectar ou ao fechar a conexão com o banco de dados."""

    def __init__(self, database: str) -> None:
        if database not in _KNOWN_DATABASES:
            raise ValueError("Nome de banco desconhecido.")
        super().__init__(f"Não foi possível conectar ao {database}.")


class DatabaseQueryError(DatabaseAccessError):
    """Erro ao executar uma query — sintaxe inválida ou constraint violada."""

    def __init__(self, database: str, code: str | None = None) -> None:
        if database not in _KNOWN_DATABASES:
            raise ValueError("Nome de banco desconhecido.")
        self.code = code
        super().__init__(f"Não foi possível executar a consulta no {database}.")


class DatabaseDataError(DatabaseQueryError):
    """Documento ou registro com estrutura inválida ou inesperada."""

    def __init__(self, database: str) -> None:
        if database not in _KNOWN_DATABASES:
            raise ValueError("Nome de banco desconhecido.")
        RuntimeError.__init__(self, f"Documento inválido retornado pelo {database}.")
        self.code = None


class UnauthorizedAccessError(RuntimeError):
    """O usuário tentou acessar uma propriedade que não pertence às suas organizações."""

    def __init__(self) -> None:
        super().__init__("Acesso não autorizado ao recurso solicitado.")
