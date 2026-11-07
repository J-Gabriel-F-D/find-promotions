"""Comando ``dealhunter ui``: janela desktop opcional (Tkinter).

O comando importa Tkinter apenas quando executado. Assim ``--help`` funciona em
ambientes sem display e a instalação base continua 100% CLI.
"""

from __future__ import annotations

import typer
from rich.markup import escape

from dealhunter.cli.exit_codes import ExitCode
from dealhunter.runtime.container import RuntimeContext


def ui_command(ctx: typer.Context) -> None:
    """Abre a interface gráfica opcional (requer Tkinter e um display)."""
    rt: RuntimeContext = ctx.obj

    if rt.json_output:
        rt.error_console.print(
            "[yellow]A interface gráfica não gera saída JSON. "
            "Use os comandos da CLI com --json.[/yellow]"
        )
        raise typer.Exit(code=int(ExitCode.USAGE))

    try:
        from dealhunter.gui.app import launch
    except ImportError as exc:
        rt.error_console.print(
            "[bold red]Tkinter indisponível:[/bold red] "
            f"{escape(str(exc))}\n"
            "Instale o Tkinter do seu Python ou use os comandos da CLI."
        )
        raise typer.Exit(code=int(ExitCode.ERROR)) from exc

    from dealhunter.gui.errors import GuiUnavailable

    try:
        launch(rt)
    except GuiUnavailable as exc:
        rt.error_console.print(
            f"[bold red]Não foi possível abrir a janela:[/bold red] {escape(str(exc))}"
        )
        raise typer.Exit(code=int(ExitCode.ERROR)) from exc
