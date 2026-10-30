"""Camada de dados PostgreSQL: funções organizacionais só aceitam propriedades do próprio usuário."""

from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace

import psycopg2.errors
import pytest

from app.data import db_postgres
from app.tools.exceptions import UnauthorizedAccessError
from app.tools.models import OrganizationProperty

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
def banco(monkeypatch):
    """O usuário 1 tem as propriedades 10 e 11; o usuário 2, a 20."""
    donos = {
        1: [OrganizationProperty(10, "Filial A", "SP", "SP"), OrganizationProperty(11, "Filial B", "SP", "SP")],
        2: [OrganizationProperty(20, "Filial C", "RJ", "RJ")],
    }
    cursor = FakeCursor()

    @contextmanager
    def fake_cursor():
        yield cursor

    monkeypatch.setattr(db_postgres, "get_user_organization_properties", lambda uid: donos.get(uid, []))
    monkeypatch.setattr(db_postgres, "_cursor", fake_cursor)
    return SimpleNamespace(cursor=cursor)


# Cada item: (função, argumentos depois de user_id e property_ids).
FUNCOES_ORGANIZACIONAIS = [
    (db_postgres.organization_can_estimate, ()),
    (db_postgres.get_organization_consumption_history, (30, TODAY)),
    (db_postgres.get_organization_consumption_daily, (date(2026, 10, 1), date(2026, 10, 7))),
    (db_postgres.get_organization_last_billed_period, (TODAY,)),
    (db_postgres.get_organization_effective_rate, (TODAY,)),
]
IDS = [f.__name__ for f, _ in FUNCOES_ORGANIZACIONAIS]


@pytest.mark.parametrize("funcao, extras", FUNCOES_ORGANIZACIONAIS, ids=IDS)
def test_propriedade_de_outro_usuario_e_recusada_sem_consultar(banco, funcao, extras):
    with pytest.raises(UnauthorizedAccessError):
        funcao(1, [20], *extras)

    assert banco.cursor.executed == []


@pytest.mark.parametrize("funcao, extras", FUNCOES_ORGANIZACIONAIS, ids=IDS)
def test_lista_mista_e_recusada_por_inteiro(banco, funcao, extras):
    """Uma propriedade própria misturada com uma alheia não passa."""
    with pytest.raises(UnauthorizedAccessError):
        funcao(1, [10, 20], *extras)

    assert banco.cursor.executed == []


@pytest.mark.parametrize("funcao, extras", FUNCOES_ORGANIZACIONAIS, ids=IDS)
def test_usuario_sem_organizacao_nao_consulta_nada(banco, funcao, extras):
    with pytest.raises(UnauthorizedAccessError):
        funcao(3, [10], *extras)

    assert banco.cursor.executed == []


@pytest.mark.parametrize("funcao, extras", FUNCOES_ORGANIZACIONAIS, ids=IDS)
def test_propriedades_proprias_consultam_so_esses_ids(banco, funcao, extras):
    funcao(1, [10, 11], *extras)

    assert len(banco.cursor.executed) == 1
    _, params = banco.cursor.executed[0]
    assert params[0] == [10, 11]


@pytest.mark.parametrize("funcao, extras", FUNCOES_ORGANIZACIONAIS, ids=IDS)
def test_lista_vazia_nao_consulta_nada(banco, funcao, extras):
    funcao(1, [], *extras)

    assert banco.cursor.executed == []


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
