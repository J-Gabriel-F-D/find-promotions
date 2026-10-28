"""Comando ``dealhunter history``."""

from __future__ import annotations

from typing import Annotated

import typer

from dealhunter.cli.exit_codes import ExitCode
from dealhunter.cli.render import emit_json
from dealhunter.cli.render.history import history_payload, render_history
from dealhunter.cli.wiring import run_history
from dealhunter.runtime.container import RuntimeContext


def history_command(
    ctx: typer.Context,
    term: Annotated[
        str,
        typer.Argument(help="Termo do produto, ID do produto (prd_) ou da oferta (off_)."),
    ],
    days: Annotated[int, typer.Option("--days", min=1, max=3650, help="Janela em dias.")] = 90,
) -> None:
    """Mostra a série historica de preços e as estatísticas do produto."""
    rt: RuntimeContext = ctx.obj
    report = run_history(rt, term, days=days)

    if report is None:
        rt.error_console.print(f"[yellow]Nada encontrado para: {term}[/yellow]")
        raise typer.Exit(code=int(ExitCode.NO_RESULTS))

    if rt.json_output:
        emit_json(history_payload(report))
        return

    render_history(report, rt)
