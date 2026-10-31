"""Mede o custo de abrir uma conexão por operação contra o pool (somente SELECTs de leitura).

Uso: python -m scripts.bench_pool [--ops 200] [--threads 8]
Lê a conexão de DATABASE_URL (variável do processo ou .env). Não cria nem altera nada no banco.
"""

from __future__ import annotations

import argparse
import statistics
import threading
import time

from app.data import db_postgres

QUERY = "SELECT 1;"


def _sem_pool() -> None:
    """Comportamento antigo: abre, consulta, fecha."""
    conn = db_postgres.get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT set_config('statement_timeout', %s, true);",
            (f"{db_postgres.get_settings().db_query_timeout_seconds * 1000}ms",),
        )
        cur.execute(QUERY)
        cur.fetchone()
        conn.commit()
    finally:
        conn.close()


def _com_pool() -> None:
    with db_postgres._cursor() as cur:
        cur.execute(QUERY)
        cur.fetchone()


def _sequencial(operacao, ops: int) -> list[float]:
    tempos = []
    for _ in range(ops):
        inicio = time.perf_counter()
        operacao()
        tempos.append((time.perf_counter() - inicio) * 1000)
    return tempos


def _concorrente(operacao, ops: int, threads: int) -> float:
    por_thread = max(1, ops // threads)
    inicio = time.perf_counter()
    trabalhadores = [
        threading.Thread(target=lambda: [operacao() for _ in range(por_thread)])
        for _ in range(threads)
    ]
    for trabalhador in trabalhadores:
        trabalhador.start()
    for trabalhador in trabalhadores:
        trabalhador.join()
    return (time.perf_counter() - inicio) * 1000


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ops", type=int, default=200, help="operações por cenário")
    parser.add_argument("--threads", type=int, default=8, help="threads no cenário concorrente")
    args = parser.parse_args()

    db_postgres.check_connection()  # falha cedo se o banco não responde
    _com_pool()  # aquece o pool para não medir a criação das conexões mínimas

    print(f"{args.ops} operações de '{QUERY.strip()}' em cada cenário\n")
    print(f"{'cenário':<28}{'média (ms)':>12}{'mediana (ms)':>14}{'total (ms)':>12}")
    for nome, operacao in (("uma conexão por operação", _sem_pool), ("com pool", _com_pool)):
        tempos = _sequencial(operacao, args.ops)
        print(f"{nome:<28}{statistics.mean(tempos):>12.2f}{statistics.median(tempos):>14.2f}{sum(tempos):>12.0f}")

    print(f"\n{args.threads} threads, {args.ops} operações no total")
    for nome, operacao in (("uma conexão por operação", _sem_pool), ("com pool", _com_pool)):
        total = _concorrente(operacao, args.ops, args.threads)
        print(f"{nome:<28}{'':>12}{'':>14}{total:>12.0f}")

    db_postgres.close_pool()


if __name__ == "__main__":
    main()
