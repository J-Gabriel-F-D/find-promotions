"""Reserva atômica de notificações: limite global entre conexões e instâncias."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta

from dealhunter.adapters.storage.database import Database
from dealhunter.adapters.storage.repository import SqliteRepository


def _reserve(
    repository: SqliteRepository,
    *,
    now: datetime,
    limit: int,
    channel: str = "console",
) -> int | None:
    return repository.reserve_notification(
        event_id=None,
        channel=channel,
        destination=None,
        subject="teste",
        body="corpo",
        now=now,
        since=now - timedelta(hours=1),
        limit=limit,
    )


def _count(database: Database) -> int:
    with database.connect() as connection:
        return int(connection.execute("SELECT COUNT(*) FROM notification").fetchone()[0])


def test_limite_de_zero_nao_reserva(database: Database, clock) -> None:
    repo = SqliteRepository(database)

    assert _reserve(repo, now=clock.now(), limit=0) is None
    assert _reserve(repo, now=clock.now(), limit=-1) is None
    assert _count(database) == 0


def test_reserva_respeita_limite_na_mesma_janela(database: Database, clock) -> None:
    repo = SqliteRepository(database)
    now = clock.now()

    ids = [_reserve(repo, now=now, limit=3) for _ in range(5)]

    assert sum(identifier is not None for identifier in ids) == 3
    assert _count(database) == 3


def test_janela_antiga_nao_consome_limite(database: Database, clock) -> None:
    repo = SqliteRepository(database)
    now = clock.now()

    assert _reserve(repo, now=now, limit=1) is not None
    assert _reserve(repo, now=now, limit=1) is None
    # A janela de contagem é rolante: uma hora depois o limite reabre.
    assert _reserve(repo, now=now + timedelta(hours=1, seconds=1), limit=1) is not None


def test_concorrencia_entre_instancias_nao_ultrapassa_o_limite(database: Database, clock) -> None:
    now = clock.now()
    limit = 4
    workers = 16
    barrier = threading.Barrier(workers)
    results: list[int | None] = []
    results_lock = threading.Lock()

    def worker() -> None:
        # Cada thread tem sua própria conexão/instância, como processos
        # distintos do monitor compartilhando o mesmo banco.
        repository = SqliteRepository(Database(database.path))
        barrier.wait(timeout=10)
        identifier = _reserve(repository, now=now, limit=limit)
        with results_lock:
            results.append(identifier)

    threads = [threading.Thread(target=worker) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert all(not thread.is_alive() for thread in threads)
    assert sum(identifier is not None for identifier in results) == limit
    assert len(results) == workers
    assert _count(database) == limit
