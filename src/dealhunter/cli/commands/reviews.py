"""Comando ``dealhunter reviews``."""

from __future__ import annotations

from typing import Annotated

import typer

from dealhunter.cli.exit_codes import ExitCode
from dealhunter.cli.render import emit_json
from dealhunter.cli.render.reviews import render_reviews, reviews_payload
from dealhunter.cli.wiring import run_reviews
from dealhunter.runtime.container import RuntimeContext


def reviews_command(
    ctx: typer.Context,
    term: Annotated[
        str,
        typer.Argument(help="Termo do produto, ID do produto (prd_) ou da oferta (off_)."),
    ],
) -> None:
    """Mostra o agregado de avaliações publicado pela fonte."""
    rt: RuntimeContext = ctx.obj
    report, warnings = run_reviews(rt, term)

    if report is None:
        for warning in warnings:
            rt.error_console.print(f"[yellow]{warning}[/yellow]")
        raise typer.Exit(code=int(ExitCode.NO_RESULTS))

    if rt.json_output:
        emit_json(reviews_payload(report, now=rt.clock.now()))
    else:
        render_reviews(report, rt)

    if not report.rows:
        raise typer.Exit(code=int(ExitCode.NO_RESULTS))
