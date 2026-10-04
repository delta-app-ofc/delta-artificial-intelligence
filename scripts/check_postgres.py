"""Verifica a conexão PostgreSQL sem depender dos provedores de LLM."""

from __future__ import annotations

import sys

from app.config import ConfigurationError
from app.data import db_postgres
from app.tools.exceptions import DatabaseAccessError


def main() -> int:
    try:
        # get_conn valida apenas a configuração PostgreSQL antes de chamar o driver.
        db_postgres.check_connection()
    except ConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except DatabaseAccessError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception:
        # O script pode ser usado em CI. Nunca imprima mensagens inesperadas
        # que possam conter dados da configuração ou do driver.
        print("Falha inesperada ao verificar o PostgreSQL.", file=sys.stderr)
        return 1

    print("PostgreSQL disponível: SELECT 1 retornou 1.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
