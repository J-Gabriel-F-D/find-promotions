"""Comando ``dealhunter monitor``: execução contínua ou um ciclo único."""

from __future__ import annotations

from typing import Annotated, Any

import typer
from rich.markup import escape

from dealhunter.adapters.sources.registry import KNOWN_SOURCES
from dealhunter.adapters.storage.lock import FileLock, LockUnavailable
from dealhunter.adapters.storage.repository import SqliteRepository
from dealhunter.application.use_cases.alerts import AlertOutcome
from dealhunter.application.use_cases.monitor import MonitorCycle, MonitorRunResult
from dealhunter.cli.exit_codes import ExitCode
from dealhunter.cli.render import emit_json, envelope
from dealhunter.cli.wiring import ensure_database, run_monitor
from dealhunter.runtime.container import RuntimeContext
from dealhunter.runtime.logging import redact_text


def _outcome_payload(outcome: AlertOutcome) -> dict[str, Any]:
    return {
        "alert_id": outcome.alert_id,
        "label": outcome.label,
        "matched": outcome.matched,
        "offer_id": outcome.offer_id,
        "price_cents": outcome.price.cents if outcome.price else None,
        "trust_score": outcome.trust_score,
        "risk_band": outcome.risk_band,
        "analysis_confidence": outcome.analysis_confidence,
        "discount_classification": outcome.discount_classification,
        "source": outcome.source,
        "source_url": outcome.source_url,
        "offer_url": outcome.offer_url,
        "collected_at": outcome.collected_at,
        "confidence": outcome.confidence,
        "channels": [
            {"channel": channel, "ok": ok, "error": error}
            for channel, ok, error in outcome.channels_sent
        ],
        "note": outcome.note,
    }


def _cycle_payload(cycle: MonitorCycle) -> dict[str, Any]:
    return {
        "run_id": cycle.run_id,
        "started_at": cycle.started_at,
        "finished_at": cycle.finished_at,
        "status": cycle.status,
        "checked": cycle.checked,
        "matched": cycle.matched,
        "notifications": cycle.notifications,
        "skipped_cooldown": cycle.skipped_cooldown,
        "note": cycle.note,
        "outcomes": [_outcome_payload(outcome) for outcome in cycle.outcomes],
    }


def _print_cycle(rt: RuntimeContext, cycle: MonitorCycle) -> None:
    if cycle.status == "error":
        rt.error_console.print(f"[red]Ciclo com erro: {escape(cycle.note)}[/red]")
        return
    if rt.quiet:
        # `--quiet` silencia o terminal, mas os canais externos continuam
        # enviando: apenas o ruído de apresentação é suprimido.
        return
    if cycle.status == "quiet":
        rt.console.print(f"[dim]{escape(cycle.note)}[/dim]")
        return
    if not cycle.outcomes:
        if cycle.skipped_cooldown:
            rt.console.print(
                f"[dim]Nenhum alerta verificado neste ciclo; "
                f"{cycle.skipped_cooldown} em cooldown.[/dim]"
            )
        else:
            rt.console.print("[dim]Nenhum alerta ativo.[/dim]")
        return

    for outcome in cycle.outcomes:
        if not outcome.matched:
            rt.console.print(
                f"[dim]#{outcome.alert_id} {escape(outcome.label)}: {escape(outcome.note)}[/dim]"
            )
            continue
        rt.console.print(
            f"[bold green]#{outcome.alert_id}[/bold green] {escape(outcome.label)}: "
            f"{outcome.price} — {escape(outcome.note)}"
        )
        if outcome.trust_score is not None:
            coverage = outcome.analysis_confidence or 0.0
            rt.console.print(
                f"  confiança {outcome.trust_score:.0f}/100; risco {outcome.risk_band}; "
                f"cobertura {coverage:.0%}"
            )
        for channel, ok, error in outcome.channels_sent:
            mark = "[green]ok[/green]" if ok else f"[red]falhou ({escape(error or '')})[/red]"
            rt.console.print(f"  {escape(channel)}: {mark}")


def _summary(rt: RuntimeContext, result: MonitorRunResult) -> None:
    if rt.quiet:
        return
    rt.console.print(
        f"[dim]{len(result.cycles)} ciclo(s); {result.checked} alerta(s) verificado(s); "
        f"{result.matched} correspondência(s); {result.notifications} envio(s); "
        f"{result.skipped_cooldown} em cooldown[/dim]"
    )
    for warning in result.warnings:
        rt.console.print(f"[yellow]! {escape(warning)}[/yellow]")


def monitor_command(
    ctx: typer.Context,
    once: Annotated[
        bool,
        typer.Option("--once", help="Executa um único ciclo e sai (ideal para cron)."),
    ] = False,
    interval: Annotated[
        int | None,
        typer.Option("--interval", min=0, help="Intervalo entre ciclos, em segundos."),
    ] = None,
    cycles: Annotated[
        int | None,
        typer.Option("--cycles", min=1, help="Número finito de ciclos (padrão: infinito)."),
    ] = None,
    source: Annotated[
        list[str] | None,
        typer.Option("--source", "-s", help="Fonte habilitada (repetível)."),
    ] = None,
    ignore_quiet_hours: Annotated[
        bool,
        typer.Option("--ignore-quiet-hours", help="Ignora a janela de silêncio configurada."),
    ] = False,
) -> None:
    """Monitora alertas continuamente, com lock, quiet hours e estado persistido."""
    rt: RuntimeContext = ctx.obj
    ensure_database(rt)

    if once and cycles is not None:
        raise typer.BadParameter("use --once ou --cycles, não os dois")
    finite = once or cycles is not None
    if rt.json_output and not finite:
        raise typer.BadParameter("--json exige --once ou --cycles para produzir um documento")
    unknown = sorted({name for name in (source or []) if name not in KNOWN_SOURCES})
    if unknown:
        raise typer.BadParameter(
            f"fonte desconhecida: {', '.join(unknown)} (conhecidas: {', '.join(KNOWN_SOURCES)})"
        )

    repository = SqliteRepository(rt.database)
    previous = repository.last_monitor_run()

    rt.paths.ensure_directories()
    lock = FileLock(rt.paths.lock_file)
    try:
        lock.acquire()
    except (LockUnavailable, OSError) as exc:
        detail = (
            str(exc)
            if isinstance(exc, LockUnavailable)
            else "não foi possível adquirir o lock do monitor"
        )
        if rt.json_output:
            emit_json(
                envelope(
                    "monitor",
                    generated_at=rt.clock.now().isoformat(),
                    status="locked",
                    locked=True,
                    error=detail,
                )
            )
        else:
            rt.error_console.print(f"[red]{escape(detail)}[/red]")
        raise typer.Exit(code=int(ExitCode.ERROR)) from exc

    try:
        callback = None if rt.json_output else (lambda cycle: _print_cycle(rt, cycle))
        result = run_monitor(
            rt,
            once=once,
            interval_seconds=interval,
            cycles=cycles,
            sources=source,
            ignore_quiet_hours=ignore_quiet_hours,
            on_cycle=callback,
        )
    except Exception as exc:  # noqa: BLE001 - CLI não deve vazar traceback
        detail = redact_text(f"{type(exc).__name__}: {exc}")
        if rt.json_output:
            emit_json(
                envelope(
                    "monitor",
                    generated_at=rt.clock.now().isoformat(),
                    status="error",
                    error=detail,
                )
            )
        else:
            rt.error_console.print(f"[red]Falha no monitor: {escape(detail)}[/red]")
        raise typer.Exit(code=int(ExitCode.ERROR)) from exc
    finally:
        lock.release()

    if rt.json_output:
        emit_json(
            envelope(
                "monitor",
                generated_at=rt.clock.now().isoformat(),
                run_id=result.run_id,
                trigger=result.trigger,
                status=result.status,
                started_at=result.started_at,
                finished_at=result.finished_at,
                previous_run=previous,
                totals={
                    "checked": result.checked,
                    "matched": result.matched,
                    "notifications": result.notifications,
                    "skipped_cooldown": result.skipped_cooldown,
                },
                cycles=[_cycle_payload(cycle) for cycle in result.cycles],
                error=result.error,
                warnings=list(result.warnings),
            )
        )
    else:
        _summary(rt, result)

    if result.status == "error":
        raise typer.Exit(code=int(ExitCode.ERROR))
