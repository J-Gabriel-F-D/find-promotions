"""Comandos ``dealhunter secrets`` -- credenciais no keyring do sistema.

Os valores nunca aparecem em stdout, JSON, logs ou histórico de shell. Em
automação use ``--stdin``; o modo interativo usa prompt oculto.
"""

from __future__ import annotations

import os
import sys
from typing import Annotated, Any

import typer
from rich import box
from rich.markup import escape
from rich.table import Table

from dealhunter.cli.exit_codes import ExitCode
from dealhunter.cli.render import emit_json, envelope
from dealhunter.runtime.config import AppConfig
from dealhunter.runtime.container import RuntimeContext
from dealhunter.runtime.secrets import SecretStore, is_valid_secret_name

app = typer.Typer(
    help="Armazena e remove segredos no keyring do sistema (nunca no TOML).",
    no_args_is_help=True,
)


def _names(config: AppConfig) -> tuple[str, ...]:
    candidates = (
        config.notifications.smtp_password_env,
        config.sources.mercadolivre_token_env,
        config.ai.api_key_env,
    )
    return tuple(dict.fromkeys(candidates))


def _store() -> SecretStore:
    return SecretStore(environ=os.environ)


def _validate_name(name: str, config: AppConfig) -> None:
    if not is_valid_secret_name(name) or name not in _names(config):
        raise typer.BadParameter(
            "nome não configurado; use um dos nomes mostrados por 'secrets status'"
        )


def _status_rows(store: SecretStore, config: AppConfig) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in _names(config):
        source = store.source(name)
        rows.append(
            {
                "name": name,
                "valid_name": is_valid_secret_name(name),
                "source": source,
                "configured": source is not None,
            }
        )
    return rows


@app.command("status")
def status(ctx: typer.Context) -> None:
    """Mostra quais segredos existem no ambiente ou no keyring, sem revelar valores."""
    rt: RuntimeContext = ctx.obj
    store = _store()
    rows = _status_rows(store, rt.config)
    available = store.keyring_available

    if rt.json_output:
        emit_json(
            envelope(
                "secrets.status",
                generated_at=rt.clock.now().isoformat(),
                keyring_available=available,
                secrets=rows,
            )
        )
        return

    table = Table(box=box.SIMPLE_HEAD, show_edge=False)
    table.add_column("Segredo", style="bold")
    table.add_column("Origem")
    for row in rows:
        if not row["valid_name"]:
            origin = "[red]nome inválido[/red]"
        elif row["source"] == "env":
            origin = "[green]variável de ambiente[/green]"
        elif row["source"] == "keyring":
            origin = "[green]keyring[/green]"
        else:
            origin = "[dim]não configurado[/dim]"
        table.add_row(escape(str(row["name"])), origin)
    rt.console.print(table)

    if not available:
        rt.console.print(
            "[yellow]! keyring indisponível; instale com "
            "'pip install dealhunter\\[secrets]'.[/yellow]"
        )


@app.command("set")
def set_secret(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Nome do segredo configurado.")],
    stdin: Annotated[
        bool,
        typer.Option("--stdin", help="Lê o valor da entrada padrão em vez de perguntar."),
    ] = False,
) -> None:
    """Grava um segredo no keyring do sistema."""
    rt: RuntimeContext = ctx.obj
    _validate_name(name, rt.config)
    store = _store()
    if not store.keyring_available:
        rt.error_console.print(
            "[red]Keyring indisponível. Instale 'dealhunter\\[secrets]' e tente novamente.[/red]"
        )
        raise typer.Exit(code=int(ExitCode.ERROR))

    if rt.json_output and not stdin:
        rt.error_console.print(
            "[red]Em modo --json use --stdin para não misturar o prompt com o JSON.[/red]"
        )
        raise typer.Exit(code=int(ExitCode.ERROR))

    if store.source(name) == "env":
        rt.error_console.print(
            "[yellow]! A variável de ambiente tem precedência e continuará sendo usada.[/yellow]"
        )

    if stdin:
        value = sys.stdin.read().rstrip("\r\n")
    else:
        value = typer.prompt("Valor do segredo", hide_input=True, confirmation_prompt=True)

    try:
        store.set(name, value)
    except (ValueError, RuntimeError) as exc:
        rt.error_console.print(f"[red]Não foi possível gravar o segredo: {escape(str(exc))}[/red]")
        raise typer.Exit(code=int(ExitCode.ERROR)) from exc

    if rt.json_output:
        emit_json(
            envelope(
                "secrets.set",
                generated_at=rt.clock.now().isoformat(),
                name=name,
                stored=True,
                active_source=store.source(name),
            )
        )
        return
    rt.console.print(f"[green]Segredo {escape(name)} gravado no keyring.[/green]")


@app.command("delete")
def delete_secret(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Nome do segredo configurado.")],
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Confirma a remoção do segredo."),
    ] = False,
) -> None:
    """Remove um segredo do keyring."""
    rt: RuntimeContext = ctx.obj
    _validate_name(name, rt.config)
    if not yes:
        raise typer.BadParameter("confirme com --yes para remover o segredo")
    store = _store()
    if not store.keyring_available:
        rt.error_console.print(
            "[red]Keyring indisponível. Instale 'dealhunter\\[secrets]' e tente novamente.[/red]"
        )
        raise typer.Exit(code=int(ExitCode.ERROR))
    removed = store.delete(name)
    if not removed:
        rt.error_console.print("[red]Segredo não encontrado no keyring.[/red]")
        raise typer.Exit(code=int(ExitCode.ERROR))

    if rt.json_output:
        emit_json(
            envelope(
                "secrets.delete",
                generated_at=rt.clock.now().isoformat(),
                name=name,
                deleted=True,
                active_source=store.source(name),
            )
        )
        return
    rt.console.print(f"[green]Segredo {escape(name)} removido do keyring.[/green]")
    if store.source(name) == "env":
        rt.console.print("[dim]A variável de ambiente correspondente continua definida.[/dim]")
