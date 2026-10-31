"""Camada de dados PostgreSQL: o user_id vai ao banco, que filtra as propriedades do usuário."""

from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace

import psycopg2.errors
import pytest

from app.data import db_postgres

TODAY = date(2026, 10, 25)


class FakeCursor:
    def __init__(self, rows=None, error=None):
        self.executed = []
        self.rows = rows or []
        self.error = error

    def execute(self, sql, params=None):
        if self.error:
            raise self.error
        self.executed.append((sql, params))

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


@pytest.fixture
def database(monkeypatch):
    """Cursor falso; qualquer consulta extra de autorização na API derruba o teste."""
    cursor = FakeCursor()

    @contextmanager
    def fake_cursor():
        yield cursor

    def sem_consulta_extra(user_id):
        raise AssertionError("a autorização é do banco: não deve haver consulta extra")

    monkeypatch.setattr(db_postgres, "get_user_organization_properties", sem_consulta_extra)
    monkeypatch.setattr(db_postgres, "_cursor", fake_cursor)
    return SimpleNamespace(cursor=cursor)


# Cada item: (função, argumentos depois de user_id e property_ids).
ORGANIZATION_FUNCTIONS = [
    (db_postgres.organization_can_estimate, ()),
    (db_postgres.get_organization_consumption_history, (30, TODAY)),
    (db_postgres.get_organization_consumption_daily, (date(2026, 10, 1), date(2026, 10, 7))),
    (db_postgres.get_organization_last_billed_period, (TODAY,)),
    (db_postgres.get_organization_effective_rate, (TODAY,)),
]
IDS = [f.__name__ for f, _ in ORGANIZATION_FUNCTIONS]


@pytest.mark.parametrize("function, extras", ORGANIZATION_FUNCTIONS, ids=IDS)
def test_user_id_e_ids_vao_ao_banco_numa_unica_consulta(database, function, extras):
    """Ids de outra organização não são checados na API: o banco os descarta junto com o dono."""
    function(1, [10, 20], *extras)

    assert len(database.cursor.executed) == 1
    _, params = database.cursor.executed[0]
    assert params[0] == 1 and params[1] == [10, 20]


@pytest.mark.parametrize("function, extras", ORGANIZATION_FUNCTIONS, ids=IDS)
def test_consulta_usa_o_filtro_de_dono_do_banco(database, function, extras):
    function(1, [10], *extras)

    sql, _ = database.cursor.executed[0]
    assert "fn_organization_" in sql or "fn_user_authorized_property_ids" in sql


@pytest.mark.parametrize("function, extras", ORGANIZATION_FUNCTIONS, ids=IDS)
def test_lista_vazia_nao_consulta_nada(database, function, extras):
    function(1, [], *extras)

    assert database.cursor.executed == []


def test_cadastro_de_habito_recusado_nao_vaza_a_mensagem_do_banco(monkeypatch):
    class ErroDoBanco(psycopg2.errors.RaiseException):
        @property
        def diag(self):
            return SimpleNamespace(message_primary="tabela tb_habit_interna violou a constraint x")

    cursor = FakeCursor(error=ErroDoBanco("falha"))

    @contextmanager
    def fake_cursor():
        yield cursor

    monkeypatch.setattr(db_postgres, "_cursor", fake_cursor)

    with pytest.raises(ValueError) as erro:
        db_postgres.create_habit(1, "BANHO LONGO", 3, ["SEGUNDA"])

    assert "tb_habit_interna" not in str(erro.value)
    assert "constraint" not in str(erro.value)
