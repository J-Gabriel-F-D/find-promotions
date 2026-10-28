"""Comando ``dealhunter sources``."""

from __future__ import annotations

import typer
from rich import box
from rich.table import Table

from dealhunter.adapters.sources.registry import KNOWN_SOURCES
from dealhunter.cli.render import emit_json, envelope
from dealhunter.runtime.container import RuntimeContext

REQUIREMENTS = {
    "mercadolivre": "API oficial; token opcional via DEALHUNTER_MELI_ACCESS_TOKEN",
    "feed": "requer sources.feed_urls; respeita robots.txt",
    "fixture": "offline; dados fictícios de demonstração",
}

app = typer.Typer(help="Lista e inspeciona as fontes de coleta.", no_args_is_help=True)


@app.command("list")
def list_sources(ctx: typer.Context) -> None:
    """Mostra fontes conhecidas e quais estao habilitadas."""
    rt: RuntimeContext = ctx.obj
    settings = rt.config.sources
    rows = [
        {
            "id": source_id,
            "enabled": source_id in settings.enabled and source_id not in settings.disabled,
            "requirement": REQUIREMENTS.get(source_id, ""),
        }
        for source_id in KNOWN_SOURCES
    ]

    if rt.json_output:
        emit_json(
            envelope(
                "sources.list",
                generated_at=rt.clock.now().isoformat(),
                sources=rows,
                respect_robots=settings.respect_robots,
                user_agent=settings.user_agent,
            )
        )
        return

    table = Table(box=box.SIMPLE_HEAD, show_edge=False)
    table.add_column("Fonte", style="bold")
    table.add_column("Status")
    table.add_column("Requisito", style="dim")
    for row in rows:
        status = "[green]habilitada[/green]" if row["enabled"] else "[dim]desabilitada[/dim]"
        table.add_row(str(row["id"]), status, str(row["requirement"]))
    rt.console.print(table)
    rt.console.print(
        f"[dim]robots.txt: {'respeitado' if settings.respect_robots else 'IGNORADO'}[/dim]"
    )
