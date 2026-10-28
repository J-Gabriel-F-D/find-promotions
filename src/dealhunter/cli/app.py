"""Raiz da CLI.

A CLI e apenas a camada de apresentacao: ela valida entrada, monta o
``RuntimeContext`` e delega para casos de uso. Nenhuma regra de negocio aqui.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from dealhunter import __version__
from dealhunter.cli.commands import config as config_cmd
from dealhunter.cli.commands import db as db_cmd
from dealhunter.cli.commands.status import status_command
from dealhunter.cli.exit_codes import ExitCode
from dealhunter.runtime.config import ConfigError
from dealhunter.runtime.container import RuntimeFlags, build_runtime

app = typer.Typer(
    name="dealhunter",
    help=(
        "Busca, compara, analisa a confiabilidade e monitora ofertas da internet.\n\n"
        "A IA e opcional: sem chave configurada, a interpretacao usa um parser "
        "deterministico."
    ),
    no_args_is_help=True,
    invoke_without_command=True,
    add_completion=False,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)

app.add_typer(config_cmd.app, name="config")
app.add_typer(db_cmd.app, name="db")
app.command("status", help="Diagnostico do ambiente local (versao, banco, fontes, IA).")(
    status_command
)


def _print_version() -> None:
    typer.echo(f"dealhunter {__version__}")


@app.callback()
def root(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option("--version", "-V", help="Mostra a versao e sai.", is_eager=True),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Saida JSON no stdout (para automacao)."),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="Modo silencioso: apenas eventos relevantes."),
    ] = False,
    debug: Annotated[
        bool,
        typer.Option("--debug", help="Log detalhado no stderr (nunca expoe segredos)."),
    ] = False,
    no_color: Annotated[
        bool,
        typer.Option("--no-color", help="Desativa cores no terminal."),
    ] = False,
    no_unicode: Annotated[
        bool,
        typer.Option("--no-unicode", help="Usa apenas ASCII (terminais limitados)."),
    ] = False,
    no_ai: Annotated[
        bool,
        typer.Option("--no-ai", help="Desliga a IA mesmo se configurada."),
    ] = False,
    config_file: Annotated[
        Path | None,
        typer.Option("--config", help="Caminho de um TOML especifico (tem precedencia)."),
    ] = None,
) -> None:
    """Flags globais aplicadas a todos os comandos."""
    if version:
        _print_version()
        raise typer.Exit(code=ExitCode.OK)

    flags = RuntimeFlags(
        json_output=json_output,
        quiet=quiet,
        debug=debug,
        no_color=no_color,
        no_unicode=no_unicode,
        ai_disabled=no_ai,
    )
    try:
        runtime = build_runtime(config_path=config_file, flags=flags)
    except ConfigError as exc:
        Console(stderr=True).print(f"[bold red]Erro de configuracao:[/bold red] {exc}")
        raise typer.Exit(code=int(ExitCode.CONFIG_ERROR)) from exc

    ctx.obj = runtime

    # `dealhunter --json` (sem comando) deve explicar o uso, nao falhar em silencio.
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(code=int(ExitCode.OK))


def main() -> None:
    """Entry point instalado como ``dealhunter``."""
    try:
        app(prog_name="dealhunter")
    except ConfigError as exc:
        Console(stderr=True).print(f"[bold red]Erro de configuracao:[/bold red] {exc}")
        raise SystemExit(int(ExitCode.CONFIG_ERROR)) from exc
    except KeyboardInterrupt:
        Console(stderr=True).print("\n[dim]Interrompido pelo usuario.[/dim]")
        raise SystemExit(int(ExitCode.INTERRUPTED)) from None


if __name__ == "__main__":
    main()
