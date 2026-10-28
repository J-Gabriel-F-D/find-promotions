"""Comando ``dealhunter db`` -- manutencao do banco local."""

from __future__ import annotations

import typer

from dealhunter.cli.render import emit_json, envelope
from dealhunter.runtime.container import RuntimeContext

app = typer.Typer(help="Gerencia o banco local (SQLite).", no_args_is_help=True)


@app.command("migrate")
def migrate(ctx: typer.Context) -> None:
    """Cria/atualiza o schema do banco local."""
    rt: RuntimeContext = ctx.obj
    rt.paths.ensure_directories()
    result = rt.database.migrate()
    version = rt.database.schema_version()

    if rt.json_output:
        emit_json(
            envelope(
                "db.migrate",
                generated_at=rt.clock.now().isoformat(),
                applied=list(result.applied),
                schema_version=version,
                database=str(rt.database.path),
            )
        )
        return

    if result.changed:
        rt.console.print(f"[green]Migracoes aplicadas:[/green] {', '.join(result.applied)}")
    else:
        rt.console.print("[dim]Nenhuma migracao pendente.[/dim]")
    rt.console.print(f"Schema atual: [bold]{version}[/bold]")
    rt.console.print(f"Banco: {rt.database.path}")


@app.command("info")
def info(ctx: typer.Context) -> None:
    """Mostra tamanho, schema e integridade do banco."""
    rt: RuntimeContext = ctx.obj
    data = {
        "path": str(rt.database.path),
        "initialized": rt.database.exists,
        "schema_version": rt.database.schema_version(),
        "size_bytes": rt.database.size_bytes(),
        "integrity_ok": rt.database.integrity_check() if rt.database.exists else None,
    }
    if rt.json_output:
        emit_json(envelope("db.info", generated_at=rt.clock.now().isoformat(), **data))
        return
    for key, value in data.items():
        rt.console.print(f"[bold]{key:<14}[/bold] {value}")
