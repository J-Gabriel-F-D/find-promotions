"""Comando ``dealhunter promotions``."""

from __future__ import annotations

from typing import Annotated

import typer

from dealhunter.cli.exit_codes import ExitCode
from dealhunter.cli.render import emit_json
from dealhunter.cli.render.promotions import promotions_payload, render_promotions
from dealhunter.cli.wiring import run_promotions
from dealhunter.runtime.container import RuntimeContext


def promotions_command(
    ctx: typer.Context,
    show_all: Annotated[bool, typer.Option("--all", help="Inclui promoções encerradas.")] = False,
    source: Annotated[
        str | None, typer.Option("--source", "-s", help="Fonte específica (ex.: fixture).")
    ] = None,
    expiring_in: Annotated[
        int | None,
        typer.Option(
            "--expiring-in",
            min=1,
            max=720,
            help="Somente promoções que terminam nas próximas N horas.",
        ),
    ] = None,
) -> None:
    """Lista promoções com janela temporal coletadas nas buscas."""
    rt: RuntimeContext = ctx.obj
    report = run_promotions(rt, include_expired=show_all, source=source, expiring_hours=expiring_in)

    if rt.json_output:
        emit_json(promotions_payload(report))
    else:
        render_promotions(report, rt)

    if not report.rows:
        raise typer.Exit(code=int(ExitCode.NO_RESULTS))
