"""Soak do laço do monitor. **Opt-in e fora do CI padrão.**

Rode com ``DEALHUNTER_SOAK=1`` e, opcionalmente, ``DEALHUNTER_SOAK_CYCLES``
(padrão: 1440 ciclos, equivalentes a 24 h com intervalo de 1 minuto). O relógio
é congelado e avançado pelo ``sleep`` injetado, então o teste não espera horas
em tempo real; ele exercita o mesmo caminho de estado, cooldown e persistência
usado em produção.

Para um soak de parede (tempo real), reduza o intervalo e diminua os ciclos::

    DEALHUNTER_SOAK=1 DEALHUNTER_SOAK_CYCLES=60 pytest -m soak tests/soak
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from dealhunter.adapters.storage.database import Database
from dealhunter.adapters.storage.repository import SqliteRepository
from dealhunter.application.use_cases.alerts import AlertOutcome
from dealhunter.application.use_cases.monitor import MonitorService
from dealhunter.domain.ports.clock import FrozenClock
from dealhunter.domain.value_objects.money import Money

pytestmark = [
    pytest.mark.soak,
    pytest.mark.skipif(
        os.environ.get("DEALHUNTER_SOAK") != "1",
        reason="defina DEALHUNTER_SOAK=1 para executar o soak",
    ),
]

DEFAULT_CYCLES = 1440
MAX_CYCLES = 100_000


class FakeAlerts:
    def __init__(self) -> None:
        self.calls = 0

    async def check(
        self, alert_id: int | None = None, *, skip_alert_ids: set[int] | None = None
    ) -> list[AlertOutcome]:
        self.calls += 1
        return [
            AlertOutcome(
                alert_id=1,
                label="soak",
                matched=True,
                price=Money(150_000),
                channels_sent=(("console", True, None),),
            )
        ]


def _cycles() -> int:
    raw = os.environ.get("DEALHUNTER_SOAK_CYCLES", str(DEFAULT_CYCLES))
    try:
        cycles = int(raw)
    except ValueError:
        pytest.fail("DEALHUNTER_SOAK_CYCLES deve ser um inteiro")
    if not 1 <= cycles <= MAX_CYCLES:
        pytest.fail(f"DEALHUNTER_SOAK_CYCLES deve ficar entre 1 e {MAX_CYCLES}")
    return cycles


def test_soak_do_laco_do_monitor(database: Database) -> None:
    cycles = _cycles()
    clock = FrozenClock(datetime(2026, 3, 15, 12, 0, tzinfo=UTC))
    alerts = FakeAlerts()
    service = MonitorService(
        repository=SqliteRepository(database),
        alerts=cast(Any, alerts),
        clock=clock,
        interval_seconds=60,
        quiet_hours_start="22:00",
        quiet_hours_end="07:00",
        timezone="UTC",
        cooldown_minutes=0,
    )

    async def fake_sleep(seconds: float) -> None:
        clock.advance(seconds=seconds)

    result = asyncio.run(service.run(cycles=cycles, ignore_quiet_hours=True, sleep=fake_sleep))

    assert len(result.cycles) == cycles
    assert result.status == "ok"
    assert result.checked == cycles
    assert alerts.calls == cycles

    repository = SqliteRepository(database)
    summary = repository.last_monitor_run()
    assert summary is not None
    assert summary["status"] == "ok"
    assert summary["cycles"] == cycles
    assert summary["alerts_checked"] == cycles
    assert repository.get_monitor_state("last_status") == "ok"
    assert repository.get_monitor_state("last_run_id") == str(result.run_id)


def test_soak_nao_deixa_execucao_em_aberto(database: Database) -> None:
    cycles = min(_cycles(), 120)
    clock = FrozenClock(datetime(2026, 3, 15, 12, 0, tzinfo=UTC))
    service = MonitorService(
        repository=SqliteRepository(database),
        alerts=cast(Any, FakeAlerts()),
        clock=clock,
        interval_seconds=0,
        quiet_hours_start="00:00",
        quiet_hours_end="00:00",
        timezone="UTC",
        cooldown_minutes=0,
    )

    async def fake_sleep(_seconds: float) -> None:
        return None

    result = asyncio.run(service.run(cycles=cycles, sleep=fake_sleep))

    with database.connect() as connection:
        running = connection.execute(
            "SELECT COUNT(*) FROM monitor_run WHERE status = 'running'"
        ).fetchone()[0]
    assert running == 0
    assert result.status == "ok"
