"""Caso de uso: monitoramento contínuo de alertas.

O monitor **reutiliza** ``AlertService.check``: não duplica regras, dedupe nem
outbox. Ele acrescenta o que é específico de execução contínua:

* quiet hours no fuso configurado (sem buscas nem notificações);
* intervalo entre ciclos;
* cooldown por alerta (evita repetir notificações fora da faixa de preço);
* lock de processo feito pela CLI;
* estado e histórico em ``monitor_run``/``monitor_state``;
* callback por ciclo para a camada de apresentação.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta, tzinfo
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dealhunter.adapters.storage.repository import SqliteRepository, iso
from dealhunter.application.use_cases.alerts import AlertOutcome, AlertService
from dealhunter.domain.ports.clock import Clock
from dealhunter.runtime.logging import redact_text

MonitorStatus = Literal["ok", "quiet", "error", "interrupted", "running"]
Sleep = Callable[[float], Awaitable[object]]
CycleCallback = Callable[["MonitorCycle"], None]


@dataclass(frozen=True, slots=True)
class MonitorCycle:
    run_id: int
    started_at: str
    finished_at: str
    status: MonitorStatus
    checked: int = 0
    matched: int = 0
    notifications: int = 0
    skipped_cooldown: int = 0
    outcomes: tuple[AlertOutcome, ...] = ()
    note: str = ""


@dataclass(frozen=True, slots=True)
class MonitorRunResult:
    run_id: int
    trigger: str
    started_at: str
    finished_at: str
    status: MonitorStatus
    cycles: tuple[MonitorCycle, ...]
    checked: int
    matched: int
    notifications: int
    skipped_cooldown: int
    error: str | None = None
    warnings: tuple[str, ...] = ()


def _parse_hour(value: str) -> time | None:
    try:
        hour, minute = value.strip().split(":")
        return time(int(hour), int(minute))
    except (ValueError, AttributeError):
        return None


def _zone(name: str) -> tzinfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        # Sem banco IANA (Windows mínimo/servidor enxuto), usa o fuso local em
        # vez de derrubar o monitor. O pacote ``tzdata`` é dependência e cobre
        # o caso normal.
        return datetime.now().astimezone().tzinfo or UTC


class MonitorService:
    def __init__(
        self,
        *,
        repository: SqliteRepository,
        alerts: AlertService,
        clock: Clock,
        interval_seconds: int = 600,
        quiet_hours_start: str = "22:00",
        quiet_hours_end: str = "07:00",
        timezone: str = "America/Sao_Paulo",
        cooldown_minutes: int = 720,
    ) -> None:
        self._repo = repository
        self._alerts = alerts
        self._clock = clock
        self._interval_seconds = max(0, interval_seconds)
        self._quiet_start = _parse_hour(quiet_hours_start)
        self._quiet_end = _parse_hour(quiet_hours_end)
        self._timezone = _zone(timezone)
        self._cooldown_minutes = max(0, cooldown_minutes)

    # ------------------------------------------------------------------ janela
    def in_quiet_hours(self, moment: datetime | None = None) -> bool:
        start, end = self._quiet_start, self._quiet_end
        if start is None or end is None or start == end:
            return False
        local = (moment or self._clock.now()).astimezone(self._timezone)
        current = local.time().replace(tzinfo=None)
        if start < end:
            return start <= current < end
        # Janela que cruza a meia-noite, ex.: 22:00 -> 07:00.
        return current >= start or current < end

    # ------------------------------------------------------------------ ciclos
    async def run_once(
        self,
        *,
        run_id: int,
        ignore_quiet_hours: bool = False,
        now: datetime | None = None,
    ) -> MonitorCycle:
        started = now or self._clock.now()
        started_text = iso(started)

        if not ignore_quiet_hours and self.in_quiet_hours(started):
            return MonitorCycle(
                run_id=run_id,
                started_at=started_text,
                finished_at=iso(self._clock.now()),
                status="quiet",
                note=(
                    "quiet hours ativas "
                    f"({self._quiet_start}-{self._quiet_end}); "
                    "nenhuma busca ou notificação foi executada"
                ),
            )

        skip_ids: set[int] = set()
        if self._cooldown_minutes:
            cutoff = started - timedelta(minutes=self._cooldown_minutes)
            skip_ids = self._repo.alerts_notified_since(cutoff)

        outcomes = await self._alerts.check(skip_alert_ids=skip_ids)
        finished = self._clock.now()
        notifications = sum(
            1 for outcome in outcomes for _channel, ok, _error in outcome.channels_sent if ok
        )
        return MonitorCycle(
            run_id=run_id,
            started_at=started_text,
            finished_at=iso(finished),
            status="ok",
            checked=len(outcomes),
            matched=sum(1 for outcome in outcomes if outcome.matched),
            notifications=notifications,
            skipped_cooldown=len(skip_ids),
            outcomes=tuple(outcomes),
            note="ciclo concluído",
        )

    async def run(
        self,
        *,
        cycles: int | None = None,
        trigger: str = "monitor",
        ignore_quiet_hours: bool = False,
        on_cycle: CycleCallback | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> MonitorRunResult:
        """Executa ``cycles`` ciclos (``None`` = até interrupção)."""
        started = self._clock.now()
        run_id = self._repo.start_monitor_run(trigger=trigger, now=started)
        results: list[MonitorCycle] = []
        error: str | None = None
        status: MonitorStatus = "ok"

        try:
            index = 0
            while cycles is None or index < cycles:
                try:
                    cycle = await self.run_once(
                        run_id=run_id,
                        ignore_quiet_hours=ignore_quiet_hours,
                    )
                except Exception as exc:  # noqa: BLE001 - um ciclo ruim não para o monitor
                    cycle = MonitorCycle(
                        run_id=run_id,
                        started_at=iso(self._clock.now()),
                        finished_at=iso(self._clock.now()),
                        status="error",
                        note="falha no ciclo; veja o log",
                    )
                    error = redact_text(f"{type(exc).__name__}: {exc}")[:500]
                    status = "error"

                results.append(cycle)
                if cycle.status == "quiet" and status == "ok":
                    status = "quiet"
                if cycle.status == "ok" and status == "quiet":
                    status = "ok"
                if cycle.status == "error":
                    status = "error"
                if on_cycle is not None:
                    on_cycle(cycle)

                index += 1
                if cycles is None or index < cycles:
                    await sleep(self._interval_seconds)
        except KeyboardInterrupt:
            status = "interrupted"
            raise
        finally:
            finished = self._clock.now()
            checked = sum(cycle.checked for cycle in results)
            matched = sum(cycle.matched for cycle in results)
            notifications = sum(cycle.notifications for cycle in results)
            self._repo.finish_monitor_run(
                run_id,
                status=status,
                cycles=len(results),
                alerts_checked=checked,
                matched=matched,
                notifications=notifications,
                error=error,
                now=finished,
            )
            self._repo.set_monitor_state("last_run_id", str(run_id), now=finished)
            self._repo.set_monitor_state("last_status", status, now=finished)
            self._repo.set_monitor_state("last_cycle_at", iso(finished), now=finished)
            if error:
                self._repo.set_monitor_state("last_error", error, now=finished)

        finished_at = iso(self._clock.now())
        return MonitorRunResult(
            run_id=run_id,
            trigger=trigger,
            started_at=iso(started),
            finished_at=finished_at,
            status=status,
            cycles=tuple(results),
            checked=sum(cycle.checked for cycle in results),
            matched=sum(cycle.matched for cycle in results),
            notifications=sum(cycle.notifications for cycle in results),
            skipped_cooldown=sum(cycle.skipped_cooldown for cycle in results),
            error=error,
        )
