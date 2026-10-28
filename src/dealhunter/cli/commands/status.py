"""Comando ``dealhunter status`` -- diagnóstico do ambiente local."""

from __future__ import annotations

from typing import Any

import typer
from rich import box
from rich.panel import Panel
from rich.table import Table

from dealhunter.cli.render import emit_json, envelope
from dealhunter.runtime.container import RuntimeContext, version_info


def _collect(rt: RuntimeContext) -> dict[str, Any]:
    database = rt.database
    initialized = database.exists
    schema_version = database.schema_version() if initialized else None
    return {
        **version_info(),
        "paths": rt.paths.as_dict(),
        "config": {
            "files": [str(path) for path in rt.config_load.files_read],
            "language": rt.config.general.language,
            "currency": rt.config.general.currency,
            "timezone": rt.config.general.timezone,
            "log_level": "debug" if rt.flags.debug else rt.config.general.log_level,
        },
        "database": {
            "initialized": initialized,
            "schema_version": schema_version,
            "size_bytes": database.size_bytes(),
            "integrity_ok": database.integrity_check() if initialized else None,
        },
        "ai": {
            "enabled": rt.ai_enabled,
            "model": rt.config.ai.model,
        },
        "sources": {
            "enabled": rt.config.sources.enabled,
            "disabled": rt.config.sources.disabled,
            "respect_robots": rt.config.sources.respect_robots,
        },
        "notifications": {"channels": rt.config.notifications.channels},
    }


def _render(rt: RuntimeContext, data: dict[str, Any]) -> None:
    console = rt.console
    if rt.quiet:
        state = "ok" if data["database"]["initialized"] else "não inicializado"
        console.print(f"dealhunter {data['version']} | db={state}")
        return

    console.print(
        Panel.fit(
            "[bold cyan]DEALHUNTER[/bold cyan]\n[dim]Intelligent Deal Search Engine[/dim]",
            box=box.ROUNDED,
            border_style="cyan",
        )
    )

    database = data["database"]
    db_state = (
        f"ok (schema {database['schema_version']})"
        if database["initialized"]
        else "não inicializado"
    )
    ai_state = "ativo" if data["ai"]["enabled"] else "desativado"
    sources = ", ".join(data["sources"]["enabled"]) or "(nenhuma configurada)"
    files = data["config"]["files"] or ["(padrões internos)"]

    table = Table(box=box.SIMPLE_HEAD, show_edge=False, pad_edge=False)
    table.add_column("Item", style="bold")
    table.add_column("Valor")
    table.add_row("Versão", f"{data['version']}  ({data['python']})")
    table.add_row("Plataforma", data["platform"])
    table.add_row("Diretório de dados", data["paths"]["data_dir"])
    table.add_row("Banco", f"{data['paths']['database']}  [{db_state}]")
    table.add_row("Configuração", "\n".join(files))
    table.add_row("Fuso / moeda", f"{data['config']['timezone']} / {data['config']['currency']}")
    table.add_row("Fontes", sources)
    table.add_row("IA", f"{ai_state} (opcional)")
    table.add_row("Notificações", ", ".join(data["notifications"]["channels"]))
    table.add_row("Logs", f"{data['config']['log_level']} -> {data['paths']['log_file']}")
    console.print(table)

    if not database["initialized"]:
        console.print(
            "[yellow]Banco ainda não criado.[/yellow] Rode [bold]dealhunter db migrate[/bold]."
        )


def status_command(ctx: typer.Context) -> None:
    """Mostra versão, caminhos, estado do banco, fontes e IA."""
    rt: RuntimeContext = ctx.obj
    data = _collect(rt)
    if rt.json_output:
        emit_json(envelope("status", generated_at=rt.clock.now().isoformat(), **data))
        return
    _render(rt, data)
