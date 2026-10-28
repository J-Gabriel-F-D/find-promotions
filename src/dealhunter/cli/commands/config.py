"""Comando ``dealhunter config`` -- inspecao da configuração efetiva."""

from __future__ import annotations

import typer

from dealhunter.cli.render import emit_json, envelope
from dealhunter.runtime.config import dump_config_toml, mask_config_pii
from dealhunter.runtime.container import RuntimeContext

app = typer.Typer(help="Mostra e valida a configuração efetiva.", no_args_is_help=True)


@app.command("path")
def show_paths(ctx: typer.Context) -> None:
    """Exibe os caminhos de configuração, dados, cache e logs."""
    rt: RuntimeContext = ctx.obj
    data = rt.paths.as_dict()
    if rt.json_output:
        emit_json(envelope("config.path", generated_at=rt.clock.now().isoformat(), paths=data))
        return
    for key, value in data.items():
        rt.console.print(f"[bold]{key:<12}[/bold] {value}")


@app.command("show")
def show_config(ctx: typer.Context) -> None:
    """Imprime a configuração efetiva em TOML (sem segredos)."""
    rt: RuntimeContext = ctx.obj
    if rt.json_output:
        emit_json(
            envelope(
                "config.show",
                generated_at=rt.clock.now().isoformat(),
                config=mask_config_pii(rt.config).model_dump(mode="json"),
                files=[str(path) for path in rt.config_load.files_read],
            )
        )
        return
    typer.echo(dump_config_toml(rt.config), nl=False)
