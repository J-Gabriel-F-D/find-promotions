"""Comando ``dealhunter monitor``: execução contínua ou um ciclo único."""

from __future__ import annotations

import os
import signal

# Reexecuta a própria CLI como processo destacado, sem shell.
import subprocess  # nosec B404
import sys
import time
from contextlib import suppress
from pathlib import Path
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
from dealhunter.runtime.process import (
    clear_pid,
    pid_running,
    read_pid,
    terminate_pid,
    write_pid,
)

DAEMON_CHILD_ENV = "DEALHUNTER_MONITOR_DAEMON_CHILD"
LOCK_WAIT_SECONDS = 10.0


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


def _daemon_command(
    rt: RuntimeContext,
    *,
    interval: int | None,
    sources: list[str] | None,
    ignore_quiet_hours: bool,
) -> list[str]:
    """Reconstrói a invocação do monitor para o processo filho."""
    command = [sys.executable, "-m", "dealhunter.cli.app"]
    if rt.config_path is not None:
        command += ["--config", str(rt.config_path)]
    if rt.quiet:
        command.append("--quiet")
    if rt.flags.debug:
        command.append("--debug")
    if rt.flags.no_color:
        command.append("--no-color")
    if rt.flags.no_unicode:
        command.append("--no-unicode")
    if rt.flags.ai_disabled:
        command.append("--no-ai")
    command.append("monitor")
    if interval is not None:
        command += ["--interval", str(interval)]
    for name in sources or []:
        command += ["--source", name]
    if ignore_quiet_hours:
        command.append("--ignore-quiet-hours")
    return command


def _spawn_daemon(
    rt: RuntimeContext,
    *,
    interval: int | None,
    sources: list[str] | None,
    ignore_quiet_hours: bool,
) -> subprocess.Popen[bytes]:
    command = _daemon_command(
        rt,
        interval=interval,
        sources=sources,
        ignore_quiet_hours=ignore_quiet_hours,
    )
    options: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
        "cwd": str(Path.cwd()),
        "env": {**os.environ, DAEMON_CHILD_ENV: "1"},
    }
    if os.name == "nt":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
        return subprocess.Popen(command, creationflags=flags, **options)  # nosec B603
    return subprocess.Popen(command, start_new_session=True, **options)  # nosec B603


def _daemon_payload(rt: RuntimeContext, *, status: str, **fields: Any) -> dict[str, Any]:
    return envelope(
        "monitor",
        generated_at=rt.clock.now().isoformat(),
        status=status,
        daemon=True,
        pid_file=str(rt.paths.pid_file),
        **fields,
    )


def _report_daemon(rt: RuntimeContext, payload: dict[str, Any], text: str) -> None:
    if rt.json_output:
        emit_json(payload)
    else:
        rt.console.print(text)


def _start_daemon(
    rt: RuntimeContext,
    *,
    interval: int | None,
    sources: list[str] | None,
    ignore_quiet_hours: bool,
) -> None:
    rt.paths.ensure_directories()
    existing = read_pid(rt.paths.pid_file)
    if existing is not None and pid_running(existing):
        _report_daemon(
            rt,
            _daemon_payload(rt, status="already_running", pid=existing),
            f"[yellow]O monitor já está em execução (PID {existing}).[/yellow]",
        )
        raise typer.Exit(code=int(ExitCode.ERROR))
    if existing is not None:
        clear_pid(rt.paths.pid_file)

    # Evita iniciar um segundo processo quando o lock já pertence a outro
    # monitor iniciado manualmente (sem PID file).
    guard = FileLock(rt.paths.lock_file)
    try:
        guard.acquire()
    except (LockUnavailable, OSError) as exc:
        detail = (
            str(exc)
            if isinstance(exc, LockUnavailable)
            else "não foi possível verificar o lock do monitor"
        )
        _report_daemon(
            rt,
            _daemon_payload(rt, status="already_running", error=detail),
            f"[yellow]{escape(detail)}[/yellow]",
        )
        raise typer.Exit(code=int(ExitCode.ERROR)) from exc
    else:
        guard.release()

    process = _spawn_daemon(
        rt,
        interval=interval,
        sources=sources,
        ignore_quiet_hours=ignore_quiet_hours,
    )
    try:
        write_pid(rt.paths.pid_file, process.pid)
    except OSError as exc:
        terminate_pid(process.pid)
        _report_daemon(
            rt,
            _daemon_payload(rt, status="error", error="não foi possível gravar o PID file"),
            f"[red]Falha ao iniciar o monitor: {escape(str(exc))}[/red]",
        )
        raise typer.Exit(code=int(ExitCode.ERROR)) from exc

    # Em Windows, alguns ambientes criam um "shim" de `python.exe` que inicia o
    # interpretador real como processo filho. O Popen devolve o PID do shim,
    # mas o monitor real reescreve o PID file com o próprio PID ao adquirir o
    # lock. Preferimos esse valor para que `--stop` encerre o processo certo.
    effective_pid = process.pid
    if os.name == "nt":
        deadline = time.monotonic() + 10.0
        started_at = time.monotonic()
        exited_at: float | None = None
        while time.monotonic() < deadline:
            now = time.monotonic()
            recorded = read_pid(rt.paths.pid_file)
            if recorded is not None and recorded != process.pid and pid_running(recorded):
                effective_pid = recorded
                break
            if process.poll() is not None:
                # O shim pode sair logo após criar o filho real. Esperamos o
                # filho gravar o próprio PID, sem sondar o lock (a sondagem
                # disputaria o lock justamente com a inicialização do filho).
                exited_at = exited_at if exited_at is not None else now
                if now - exited_at >= 5.0:
                    break
            elif now - started_at >= 1.0:
                # Sem shim: o processo criado já é o monitor e o PID é este.
                break
            time.sleep(0.02)
        # O filho pode ter gravado o PID real entre a última leitura e o fim
        # do laço.
        recorded = read_pid(rt.paths.pid_file)
        if recorded is not None and recorded != process.pid and pid_running(recorded):
            effective_pid = recorded

    if process.poll() is not None and not pid_running(effective_pid):
        clear_pid(rt.paths.pid_file)
        _report_daemon(
            rt,
            _daemon_payload(rt, status="error", error="o processo filho encerrou imediatamente"),
            "[red]Falha ao iniciar o monitor em segundo plano.[/red]",
        )
        raise typer.Exit(code=int(ExitCode.ERROR))

    _report_daemon(
        rt,
        _daemon_payload(rt, status="started", pid=effective_pid),
        f"[green]Monitor iniciado em segundo plano (PID {effective_pid}).[/green] "
        "Use [bold]dealhunter monitor --stop[/bold] para encerrar.",
    )


def _stop_daemon(rt: RuntimeContext) -> None:
    rt.paths.ensure_directories()
    pid = read_pid(rt.paths.pid_file)
    if pid is None:
        # Arquivo ausente, vazio ou corrompido: não há como validar o dono,
        # então removemos o resíduo para não confundir a próxima execução.
        clear_pid(rt.paths.pid_file)
        _report_daemon(
            rt,
            _daemon_payload(rt, status="not_running"),
            "[dim]Nenhum monitor em execução.[/dim]",
        )
        return

    if not pid_running(pid):
        clear_pid(rt.paths.pid_file)
        _report_daemon(
            rt,
            _daemon_payload(rt, status="not_running", stale_pid=pid),
            "[dim]PID file antigo removido; nenhum monitor em execução.[/dim]",
        )
        return

    # O PID file é auxiliar. Só encerramos se o lock do monitor estiver de fato
    # ocupado; um PID reciclado pelo sistema não deve ser morto por engano.
    guard = FileLock(rt.paths.lock_file)
    try:
        guard.acquire()
    except (LockUnavailable, OSError):
        pass
    else:
        guard.release()
        clear_pid(rt.paths.pid_file, expected_pid=pid)
        _report_daemon(
            rt,
            _daemon_payload(rt, status="not_running", stale_pid=pid),
            "[dim]PID file antigo removido; nenhum monitor em execução.[/dim]",
        )
        return

    if not terminate_pid(pid):
        _report_daemon(
            rt,
            _daemon_payload(rt, status="error", pid=pid, error="não foi possível encerrar o PID"),
            f"[red]Não foi possível encerrar o monitor (PID {pid}).[/red]",
        )
        raise typer.Exit(code=int(ExitCode.ERROR))

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and pid_running(pid):
        time.sleep(0.05)
    clear_pid(rt.paths.pid_file, expected_pid=pid)
    _report_daemon(
        rt,
        _daemon_payload(rt, status="stopped", pid=pid),
        f"[green]Monitor encerrado (PID {pid}).[/green]",
    )


def _raise_interrupt(_signum: int, _frame: object) -> None:
    raise KeyboardInterrupt


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
    daemon: Annotated[
        bool,
        typer.Option("--daemon", help="Inicia o monitor em segundo plano e retorna."),
    ] = False,
    stop: Annotated[
        bool,
        typer.Option("--stop", help="Encerra o monitor em segundo plano via PID file."),
    ] = False,
) -> None:
    """Monitora alertas continuamente, com lock, quiet hours e estado persistido."""
    rt: RuntimeContext = ctx.obj

    if daemon and stop:
        raise typer.BadParameter("use --daemon ou --stop, não os dois")
    if daemon and (once or cycles is not None):
        raise typer.BadParameter("--daemon não combina com --once/--cycles")
    if stop:
        if once or cycles is not None or interval is not None or source or ignore_quiet_hours:
            raise typer.BadParameter("--stop não aceita outras opções de execução")
        _stop_daemon(rt)
        return

    unknown = sorted({name for name in (source or []) if name not in KNOWN_SOURCES})
    if unknown:
        raise typer.BadParameter(
            f"fonte desconhecida: {', '.join(unknown)} (conhecidas: {', '.join(KNOWN_SOURCES)})"
        )

    if daemon:
        _start_daemon(
            rt,
            interval=interval,
            sources=source,
            ignore_quiet_hours=ignore_quiet_hours,
        )
        return

    ensure_database(rt)
    if once and cycles is not None:
        raise typer.BadParameter("use --once ou --cycles, não os dois")
    finite = once or cycles is not None
    if rt.json_output and not finite:
        raise typer.BadParameter("--json exige --once ou --cycles para produzir um documento")

    repository = SqliteRepository(rt.database)
    previous = repository.last_monitor_run()

    rt.paths.ensure_directories()
    lock = FileLock(rt.paths.lock_file)
    # Filho de --daemon: o pai pode estar sondando o lock no Windows. Em vez
    # de falhar na primeira disputa, tenta por alguns segundos.
    wait_until = time.monotonic()
    if os.environ.get(DAEMON_CHILD_ENV) == "1":
        wait_until += LOCK_WAIT_SECONDS
    while True:
        try:
            lock.acquire()
            break
        except (LockUnavailable, OSError) as exc:
            if time.monotonic() < wait_until:
                time.sleep(0.05)
                continue
            # Se este processo foi iniciado por --daemon, o pai já gravou nosso PID.
            clear_pid(rt.paths.pid_file, expected_pid=os.getpid())
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

    # O PID file é auxiliar; a execução contínua não depende dele.
    with suppress(OSError):
        write_pid(rt.paths.pid_file, os.getpid())

    previous_term = None
    if not finite:
        try:
            previous_term = signal.signal(signal.SIGTERM, _raise_interrupt)
        except (ValueError, OSError):
            previous_term = None

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
        if previous_term is not None:
            with suppress(ValueError, OSError):
                signal.signal(signal.SIGTERM, previous_term)
        lock.release()
        clear_pid(rt.paths.pid_file, expected_pid=os.getpid())

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
