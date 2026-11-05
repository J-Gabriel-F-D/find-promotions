"""Comando ``dealhunter reviews``."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.markup import escape

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
    include_text: Annotated[
        bool,
        typer.Option(
            "--include-text",
            help="Inclui os textos individuais publicados pela fonte (opt-in).",
        ),
    ] = False,
    limit: Annotated[
        int,
        typer.Option(
            "--limit",
            min=1,
            max=100,
            help="Máximo de textos individuais analisados/exibidos por loja.",
        ),
    ] = 20,
) -> None:
    """Mostra o agregado e a análise determinística dos textos da fonte."""
    rt: RuntimeContext = ctx.obj
    report, warnings = run_reviews(rt, term, text_limit=limit, include_text=include_text)

    if report is None:
        for warning in warnings:
            rt.error_console.print(f"[yellow]{escape(warning)}[/yellow]")
        raise typer.Exit(code=int(ExitCode.NO_RESULTS))

    if rt.json_output:
        emit_json(reviews_payload(report, now=rt.clock.now(), include_text=include_text))
    else:
        render_reviews(report, rt, include_text=include_text, limit=limit)

    if not report.rows:
        raise typer.Exit(code=int(ExitCode.NO_RESULTS))
