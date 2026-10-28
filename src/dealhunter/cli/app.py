"""Raiz da CLI.

A CLI e apenas a camada de apresentacao: ela valida entrada, monta o
``RuntimeContext`` e delega para casos de uso. Nenhuma regra de negócio aqui.
"""

from __future__ import annotations

import sys
from contextlib import suppress
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape

from dealhunter import __version__
from dealhunter.cli.commands import alerts as alerts_cmd
from dealhunter.cli.commands import config as config_cmd
from dealhunter.cli.commands import coupons as coupons_cmd
from dealhunter.cli.commands import db as db_cmd
from dealhunter.cli.commands import notify as notify_cmd
from dealhunter.cli.commands import sources as sources_cmd
from dealhunter.cli.commands.history import history_command
from dealhunter.cli.commands.promotions import promotions_command
from dealhunter.cli.commands.reviews import reviews_command
from dealhunter.cli.commands.search import search_command
from dealhunter.cli.commands.status import status_command
from dealhunter.cli.exit_codes import ExitCode
from dealhunter.runtime.config import ConfigError
from dealhunter.runtime.container import RuntimeFlags, build_runtime

app = typer.Typer(
    name="dealhunter",
    help=(
        "Busca, compara, analisa a confiabilidade e monitora ofertas da internet.\n\n"
        "A IA é opcional: sem chave configurada, a interpretação usa um parser "
        "determinístico."
    ),
    no_args_is_help=True,
    invoke_without_command=True,
    add_completion=False,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)

app.add_typer(config_cmd.app, name="config")
app.add_typer(db_cmd.app, name="db")
app.add_typer(alerts_cmd.app, name="alerts")
app.add_typer(notify_cmd.app, name="notify")
app.add_typer(sources_cmd.app, name="sources")
app.add_typer(coupons_cmd.app, name="coupons")
app.command("status", help="Diagnóstico do ambiente local (versão, banco, fontes, IA).")(
    status_command
)
app.command("search", help="Busca ofertas nas fontes habilitadas.")(search_command)
app.command("history", help="Histórico de preços e estatísticas de um produto.")(history_command)
app.command("promotions", help="Promoções com janela temporal coletadas nas buscas.")(
    promotions_command
)
app.command("reviews", help="Agregado de avaliações publicado pela fonte.")(reviews_command)


def _print_version() -> None:
    typer.echo(f"dealhunter {__version__}")


@app.callback()
def root(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option("--version", "-V", help="Mostra a versão e sai.", is_eager=True),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Saída JSON no stdout (para automação)."),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="Modo silencioso: apenas eventos relevantes."),
    ] = False,
    debug: Annotated[
        bool,
        typer.Option("--debug", help="Log detalhado no stderr (nunca expõe segredos)."),
    ] = False,
    no_color: Annotated[
        bool,
        typer.Option("--no-color", help="Desativa cores no terminal."),
    ] = False,
    no_unicode: Annotated[
        bool,
        typer.Option("--no-unicode", help="Sem símbolos/boxes Unicode (terminais limitados)."),
    ] = False,
    no_ai: Annotated[
        bool,
        typer.Option("--no-ai", help="Desliga a IA mesmo se configurada."),
    ] = False,
    config_file: Annotated[
        Path | None,
        typer.Option("--config", help="Caminho de um TOML específico (tem precedência)."),
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
        Console(stderr=True).print(f"[bold red]Erro de configuração:[/bold red] {escape(str(exc))}")
        raise typer.Exit(code=int(ExitCode.CONFIG_ERROR)) from exc

    ctx.obj = runtime

    # `dealhunter --json` (sem comando) deve explicar o uso, não falhar em silencio.
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(code=int(ExitCode.OK))


def _use_utf8_streams() -> None:
    """Força UTF-8 em stdout/stderr quando o stream não é interativo.

    Em pipe/redirecionamento o Python usa a codificação local (cp1252, cp850 no
    Windows), o que corromperia acentos — e o contrato JSON exige UTF-8.
    """
    for stream, errors in ((sys.stdout, "strict"), (sys.stderr, "replace")):
        encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if encoding == "utf8":
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        with suppress(ValueError, OSError):
            reconfigure(encoding="utf-8", errors=errors)


def main() -> None:
    """Entry point instalado como ``dealhunter``."""
    _use_utf8_streams()
    try:
        app(prog_name="dealhunter")
    except ConfigError as exc:
        Console(stderr=True).print(f"[bold red]Erro de configuração:[/bold red] {escape(str(exc))}")
        raise SystemExit(int(ExitCode.CONFIG_ERROR)) from exc
    except KeyboardInterrupt:
        Console(stderr=True).print("\n[dim]Interrompido pelo usuário.[/dim]")
        raise SystemExit(int(ExitCode.INTERRUPTED)) from None


if __name__ == "__main__":
    main()
