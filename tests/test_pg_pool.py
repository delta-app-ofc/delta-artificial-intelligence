"""Pool de conexões PostgreSQL: reuso, devolução, descarte, espera e fechamento (sem banco)."""

import os
import threading
import time
from types import SimpleNamespace

import psycopg2
import pytest

from app.config import ConfigurationError, load_settings, validate_postgres_config
from app.data import db_postgres
from app.tools.exceptions import DatabaseConnectionError, DatabaseQueryError


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.closed = False

    def execute(self, sql, params=None):
        if self.conn.break_on_start and "set_config" in sql:
            self.conn.break_on_start = False
            self.conn.closed = True
            raise psycopg2.OperationalError("conexão caiu")
        self.conn.executed.append((sql, params))

    def close(self):
        self.closed = True


class FakeConn:
    def __init__(self):
        self.closed = False
        self.break_on_start = False
        self.executed = []
        self.commits = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1


class FakePool:
    """Imita ThreadedConnectionPool: guarda as conexões livres e conta o uso simultâneo."""

    instances = []

    def __init__(self, minconn, maxconn, dsn, **kwargs):
        self.minconn, self.maxconn, self.dsn, self.kwargs = minconn, maxconn, dsn, kwargs
        self.created = []
        self.idle = []
        self.checked_out = 0
        self.max_checked_out = 0
        self.closed = False
        self.puts = []
        self.lock = threading.Lock()
        FakePool.instances.append(self)

    def getconn(self):
        with self.lock:
            conn = self.idle.pop() if self.idle else None
            if conn is None:
                conn = FakeConn()
                self.created.append(conn)
            self.checked_out += 1
            self.max_checked_out = max(self.max_checked_out, self.checked_out)
            return conn

    def putconn(self, conn, close=False):
        with self.lock:
            self.checked_out -= 1
            self.puts.append((conn, close))
            if close or conn.closed:
                conn.closed = True
            else:
                self.idle.append(conn)

    def closeall(self):
        self.closed = True
        for conn in self.created:
            conn.closed = True


@pytest.fixture
def pg(monkeypatch):
    FakePool.instances = []

    def configure(max_size=3, wait=1):
        settings = SimpleNamespace(
            db_pool_min_size=1, db_pool_max_size=max_size, db_pool_wait_seconds=wait,
            db_connect_timeout_seconds=5, db_query_timeout_seconds=30,
            database_url="postgresql://u:p@localhost:5432/db",
        )
        monkeypatch.setattr(db_postgres, "get_settings", lambda: settings)

    monkeypatch.setattr(db_postgres, "validate_postgres_config", lambda settings=None: None)
    monkeypatch.setattr(db_postgres, "ThreadedConnectionPool", FakePool)
    configure()
    db_postgres.close_pool()
    yield SimpleNamespace(configure=configure, pool=lambda: FakePool.instances[-1])
    db_postgres.close_pool()


def test_conexao_e_reaproveitada_entre_operacoes(pg):
    for _ in range(3):
        with db_postgres._cursor():
            pass

    pool = pg.pool()
    assert len(pool.created) == 1
    assert pool.created[0].commits == 3
    assert pool.checked_out == 0


def test_cada_uso_aplica_o_timeout_da_consulta(pg):
    with db_postgres._cursor():
        pass

    sql, params = pg.pool().created[0].executed[0]
    assert "set_config('statement_timeout'" in sql and params == ("30000ms",)


def test_o_pool_recebe_tamanhos_e_timeout_de_conexao(pg):
    with db_postgres._cursor():
        pass

    pool = pg.pool()
    assert pool.maxconn == 3
    assert pool.minconn == 3  # depois das conexões iniciais, mantém ociosas até o máximo
    assert pool.kwargs == {"connect_timeout": 5}


def test_erro_do_banco_vira_erro_publico_e_a_conexao_volta_ao_pool(pg):
    with pytest.raises(DatabaseQueryError):
        with db_postgres._cursor():
            raise psycopg2.DataError("detalhe interno do driver")
    with db_postgres._cursor():
        pass

    pool = pg.pool()
    assert len(pool.created) == 1  # a mesma conexão serviu as duas operações
    assert pool.checked_out == 0


def test_conexao_que_caiu_no_meio_e_descartada(pg):
    with pytest.raises(DatabaseQueryError):
        with db_postgres._cursor():
            pg.pool().created[0].closed = True  # o servidor derrubou a conexão
            raise psycopg2.OperationalError("servidor caiu")
    with db_postgres._cursor():
        pass

    pool = pg.pool()
    assert len(pool.created) == 2
    assert pool.created[0].closed is True


def test_timeout_de_consulta_nao_descarta_conexao_saudavel(pg):
    with pytest.raises(DatabaseQueryError):
        with db_postgres._cursor():
            raise psycopg2.errors.QueryCanceled("statement timeout")
    with db_postgres._cursor():
        pass

    assert len(pg.pool().created) == 1


def test_excecao_da_aplicacao_devolve_a_conexao_e_propaga(pg):
    with pytest.raises(ValueError):
        with db_postgres._cursor():
            raise ValueError("regra de negócio")

    pool = pg.pool()
    assert pool.checked_out == 0
    assert pool.created[0].closed is False


def test_conexao_quebrada_do_pool_e_trocada_uma_vez_antes_do_sql(pg):
    with db_postgres._cursor():
        pass
    pool = pg.pool()
    pool.created[0].break_on_start = True  # a próxima abertura falha ao preparar o cursor

    with db_postgres._cursor() as cur:
        assert cur is not None

    assert len(pool.created) == 2
    assert pool.checked_out == 0


def test_duas_conexoes_quebradas_seguidas_dao_erro_publico_e_liberam_o_pool(pg, monkeypatch):
    def sempre_quebrada(self):
        conn = FakeConn()
        conn.break_on_start = True
        self.created.append(conn)
        self.checked_out += 1
        return conn

    monkeypatch.setattr(FakePool, "getconn", sempre_quebrada)

    with pytest.raises(DatabaseConnectionError):
        with db_postgres._cursor():
            pass

    # o espaço do pool foi liberado: o próximo uso não fica preso esperando
    assert db_postgres._pool_slots._value == 3


def test_pool_cheio_espera_e_depois_devolve_erro_publico(pg):
    pg.configure(max_size=1, wait=1)
    db_postgres.close_pool()
    segurando = threading.Event()
    liberar = threading.Event()

    def segura():
        with db_postgres._cursor():
            segurando.set()
            liberar.wait(5)

    thread = threading.Thread(target=segura)
    thread.start()
    segurando.wait(2)
    inicio = time.monotonic()
    with pytest.raises(DatabaseConnectionError):
        with db_postgres._cursor():
            pass
    assert 0.8 <= time.monotonic() - inicio < 3
    liberar.set()
    thread.join()

    with db_postgres._cursor():  # depois que libera, volta a funcionar
        pass


def test_close_pool_fecha_tudo_e_pode_repetir(pg):
    with db_postgres._cursor():
        pass
    primeiro = pg.pool()

    db_postgres.close_pool()
    db_postgres.close_pool()

    assert primeiro.closed is True
    with db_postgres._cursor():  # um novo pool nasce no próximo uso
        pass
    assert len(FakePool.instances) == 2


def test_threads_concorrentes_nunca_passam_do_tamanho_maximo(pg):
    pg.configure(max_size=3, wait=5)
    db_postgres.close_pool()
    erros = []

    def trabalha():
        try:
            for _ in range(5):
                with db_postgres._cursor():
                    time.sleep(0.002)
        except Exception as exc:  # pragma: no cover - só para o assert abaixo
            erros.append(exc)

    threads = [threading.Thread(target=trabalha) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    pool = pg.pool()
    assert erros == []
    assert pool.max_checked_out <= 3
    assert len(pool.created) <= 3
    assert pool.checked_out == 0


@pytest.mark.parametrize("env, trecho", [
    ({"DB_POOL_MIN_SIZE": "0"}, "DB_POOL_MIN_SIZE deve ser positivo"),
    ({"DB_POOL_MIN_SIZE": "5", "DB_POOL_MAX_SIZE": "2"}, "DB_POOL_MAX_SIZE deve ser maior ou igual"),
    ({"DB_POOL_WAIT_SECONDS": "0"}, "DB_POOL_WAIT_SECONDS deve ser positivo"),
    ({"DB_POOL_MAX_SIZE": "muitos"}, "DB_POOL_MAX_SIZE"),
])
def test_configuracao_do_pool_e_validada(env, trecho):
    ambiente = {"APP_ENV": "test", "DATABASE_URL": "postgresql://u:p@localhost:5432/db", **env}
    settings = load_settings(ambiente, env_file=None)

    with pytest.raises(ConfigurationError) as erro:
        validate_postgres_config(settings=settings)

    assert trecho in str(erro.value)


def test_configuracao_padrao_do_pool():
    settings = load_settings(
        {"APP_ENV": "test", "DATABASE_URL": "postgresql://u:p@localhost:5432/db"}, env_file=None
    )

    validate_postgres_config(settings=settings)
    assert (settings.db_pool_min_size, settings.db_pool_max_size, settings.db_pool_wait_seconds) == (1, 10, 5)


# --- Postgres real, só leitura: roda apenas com DELTA_TEST_POSTGRES_URI -------------------------

REAL_URI = os.environ.get("DELTA_TEST_POSTGRES_URI")


@pytest.mark.skipif(not REAL_URI, reason="defina DELTA_TEST_POSTGRES_URI para testar com PostgreSQL real")
def test_pool_real_reaproveita_conexao_e_nao_vaza_timeout(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", REAL_URI)
    monkeypatch.setenv("DB_POOL_MAX_SIZE", "2")
    monkeypatch.setenv("DB_QUERY_TIMEOUT_SECONDS", "1")
    from app.config import get_settings

    get_settings(refresh=True)
    db_postgres.close_pool()
    try:
        with db_postgres._cursor() as cur:
            cur.execute("SELECT pg_backend_pid();")
            pid = cur.fetchone()[0]
        with pytest.raises(DatabaseQueryError):
            with db_postgres._cursor() as cur:
                cur.execute("SELECT pg_sleep(3);")
        with db_postgres._cursor() as cur:
            cur.execute("SELECT pg_backend_pid(), current_setting('statement_timeout');")
            pid_depois, timeout = cur.fetchone()
        assert pid_depois == pid  # mesma conexão, reaproveitada
        assert timeout == "1s"

        # Com várias threads, as conexões que sobem ao máximo ficam no pool, sem reconectar a cada uso.
        pids = set()
        trava = threading.Lock()

        def usa():
            for _ in range(10):
                with db_postgres._cursor() as cur:
                    cur.execute("SELECT pg_backend_pid();")
                    with trava:
                        pids.add(cur.fetchone()[0])

        threads = [threading.Thread(target=usa) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert len(pids) <= 2  # o pool real tem no máximo 2 conexões (DB_POOL_MAX_SIZE=2)
    finally:
        db_postgres.close_pool()
        get_settings(refresh=True)
