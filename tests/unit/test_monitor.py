"""Testes do monitor: quiet hours, ciclos, cooldown e estado persistido."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, cast

from dealhunter.adapters.storage.database import Database
from dealhunter.adapters.storage.repository import SqliteRepository
from dealhunter.application.use_cases.alerts import AlertOutcome
from dealhunter.application.use_cases.monitor import MonitorService
from dealhunter.domain.ports.clock import FrozenClock
from dealhunter.domain.value_objects.money import Money


class FakeAlerts:
    def __init__(
        self,
        outcomes: list[AlertOutcome] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.outcomes = outcomes or []
        self.error = error
        self.calls: list[set[int]] = []

    async def check(
        self, alert_id: int | None = None, *, skip_alert_ids: set[int] | None = None
    ) -> list[AlertOutcome]:
        self.calls.append(set(skip_alert_ids or set()))
        if self.error:
            raise self.error
        return self.outcomes


def _service(
    database: Database,
    clock: FrozenClock,
    alerts: FakeAlerts,
    **overrides: Any,
) -> MonitorService:
    values: dict[str, Any] = {
        "repository": SqliteRepository(database),
        "alerts": cast(Any, alerts),
        "clock": clock,
        "interval_seconds": 0,
        "quiet_hours_start": "22:00",
        "quiet_hours_end": "07:00",
        "timezone": "UTC",
        "cooldown_minutes": 0,
    }
    values.update(overrides)
    return MonitorService(**values)


def test_quiet_hours_cruzando_meia_noite(database: Database) -> None:
    clock = FrozenClock(datetime(2026, 3, 15, 23, 0, tzinfo=UTC))
    service = _service(database, clock, FakeAlerts())

    assert service.in_quiet_hours() is True
    assert service.in_quiet_hours(datetime(2026, 3, 15, 8, 0, tzinfo=UTC)) is False


def test_quiet_hours_diurno(database: Database) -> None:
    clock = FrozenClock(datetime(2026, 3, 15, 12, 0, tzinfo=UTC))
    service = _service(
        database, clock, FakeAlerts(), quiet_hours_start="09:00", quiet_hours_end="18:00"
    )

    assert service.in_quiet_hours() is True
    assert service.in_quiet_hours(datetime(2026, 3, 15, 19, 0, tzinfo=UTC)) is False


def test_janela_desativada_quando_inicio_igual_fim(database: Database) -> None:
    clock = FrozenClock(datetime(2026, 3, 15, 23, 0, tzinfo=UTC))
    service = _service(
        database, clock, FakeAlerts(), quiet_hours_start="00:00", quiet_hours_end="00:00"
    )

    assert service.in_quiet_hours() is False


def test_ciclo_em_quiet_hours_nao_chama_alertas(database: Database) -> None:
    clock = FrozenClock(datetime(2026, 3, 15, 23, 0, tzinfo=UTC))
    alerts = FakeAlerts([AlertOutcome(alert_id=1, label="x", matched=True)])
    service = _service(database, clock, alerts)

    result = asyncio.run(service.run(cycles=1, trigger="once"))

    assert result.status == "quiet"
    assert result.checked == 0
    assert alerts.calls == []
    summary = SqliteRepository(database).monitor_run_summary(result.run_id)
    assert summary is not None
    assert summary["status"] == "quiet"


def test_ignore_quiet_hours_executa_ciclo(database: Database) -> None:
    clock = FrozenClock(datetime(2026, 3, 15, 23, 0, tzinfo=UTC))
    alerts = FakeAlerts([AlertOutcome(alert_id=1, label="x", matched=False)])
    service = _service(database, clock, alerts)

    result = asyncio.run(service.run(cycles=1, ignore_quiet_hours=True))

    assert result.status == "ok"
    assert result.checked == 1
    assert alerts.calls == [set()]


def test_ciclos_multiplos_com_callback_e_sleep(database: Database) -> None:
    clock = FrozenClock(datetime(2026, 3, 15, 12, 0, tzinfo=UTC))
    outcome = AlertOutcome(
        alert_id=7,
        label="redmi",
        matched=True,
        price=Money(150_000),
        channels_sent=(("console", True, None),),
    )
    alerts = FakeAlerts([outcome])
    service = _service(database, clock, alerts, interval_seconds=30)
    seen: list[object] = []
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        clock.advance(seconds=seconds)

    result = asyncio.run(service.run(cycles=2, on_cycle=seen.append, sleep=fake_sleep))

    assert len(result.cycles) == 2
    assert len(seen) == 2
    assert slept == [30]
    assert result.checked == 2
    assert result.matched == 2
    assert result.notifications == 2


def test_cooldown_pula_alertas_notificados(database: Database, clock: FrozenClock) -> None:
    repo = SqliteRepository(database)
    alert_id = repo.create_alert(
        label="redmi",
        query="redmi",
        spec_json='{"product": "redmi"}',
        max_price_cents=170_000,
        min_discount_pct=None,
        channels=["console"],
        now=clock.now(),
    )
    repo.record_event(
        alert_id=alert_id,
        offer_id="off_x",
        price_cents=150_000,
        reason="teste",
        dedupe_key="evt_cooldown",
        now=clock.now(),
    )
    alerts = FakeAlerts()
    service = _service(database, clock, alerts, cooldown_minutes=720)

    result = asyncio.run(service.run_once(run_id=999))

    assert alerts.calls == [{alert_id}]
    assert result.skipped_cooldown == 1
    assert result.checked == 0


def test_erro_em_ciclo_nao_derruba_monitor(database: Database) -> None:
    clock = FrozenClock(datetime(2026, 3, 15, 12, 0, tzinfo=UTC))
    alerts = FakeAlerts(error=RuntimeError("falha simulada"))
    service = _service(database, clock, alerts)

    result = asyncio.run(service.run(cycles=2))

    assert result.status == "error"
    assert result.error is not None
    assert "RuntimeError" in result.error
    assert [cycle.status for cycle in result.cycles] == ["error", "error"]
    state = SqliteRepository(database).get_monitor_state("last_status")
    assert state == "error"


def test_estado_e_historico_persistidos(database: Database) -> None:
    clock = FrozenClock(datetime(2026, 3, 15, 12, 0, tzinfo=UTC))
    service = _service(database, clock, FakeAlerts())

    result = asyncio.run(service.run(cycles=1))

    repo = SqliteRepository(database)
    assert repo.get_monitor_state("last_run_id") == str(result.run_id)
    assert repo.get_monitor_state("last_status") == "ok"
    assert repo.get_monitor_state("last_cycle_at") is not None
    summary = repo.last_monitor_run()
    assert summary is not None
    assert summary["cycles"] == 1
    assert summary["finished_at"] is not None


def test_nova_execucao_marca_orfas_como_interrompidas(database: Database) -> None:
    repo = SqliteRepository(database)
    orphan = repo.start_monitor_run(trigger="monitor", now=datetime(2026, 3, 15, tzinfo=UTC))

    clock = FrozenClock(datetime(2026, 3, 15, 13, 0, tzinfo=UTC))
    service = _service(database, clock, FakeAlerts())
    asyncio.run(service.run(cycles=1))

    summary = repo.monitor_run_summary(orphan)
    assert summary is not None
    assert summary["status"] == "interrupted"
