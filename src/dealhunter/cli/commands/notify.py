"""Comandos ``dealhunter notify``."""

from __future__ import annotations

from typing import Annotated

import typer
from rich import box
from rich.markup import escape
from rich.table import Table

from dealhunter.adapters.notify.base import NotificationMessage, Notifier
from dealhunter.adapters.notify.registry import build_notifier
from dealhunter.cli.exit_codes import ExitCode
from dealhunter.cli.render import emit_json, envelope
from dealhunter.runtime.container import RuntimeContext

app = typer.Typer(help="Configura e testa os canais de notificação.", no_args_is_help=True)


def _notifier(rt: RuntimeContext) -> tuple[Notifier, list[str]]:
    return build_notifier(
        rt.config.notifications,
        printer=(lambda _text: None) if rt.json_output else rt.error_console.print,
    )


@app.command("status")
def status(ctx: typer.Context) -> None:
    """Mostra quais canais estao realmente disponiveis."""
    rt: RuntimeContext = ctx.obj
    notifier, warnings = _notifier(rt)

    if rt.json_output:
        emit_json(
            envelope(
                "notify.status",
                generated_at=rt.clock.now().isoformat(),
                available=list(notifier.available),
                requested=list(rt.config.notifications.channels),
                warnings=warnings,
            )
        )
        return

    table = Table(box=box.SIMPLE_HEAD, show_edge=False)
    table.add_column("Canal", style="bold")
    table.add_column("Status")
    for channel in ("console", "email"):
        available = notifier.supports(channel)
        table.add_row(
            channel,
            "[green]disponível[/green]" if available else "[dim]não configurado[/dim]",
        )
    rt.console.print(table)

    for warning in warnings:
        rt.console.print(f"[yellow]! {escape(warning)}[/yellow]")
    if not notifier.supports("email"):
        rt.console.print(
            "[dim]Para e-mail: configure [notifications] smtp_host, email_from e email_to, "
            "e defina DEALHUNTER_SMTP_PASSWORD ou use 'dealhunter secrets set'.[/dim]"
        )


@app.command("test")
def test(
    ctx: typer.Context,
    channel: Annotated[
        list[str] | None, typer.Option("--channel", help="Canal a testar (repetivel).")
    ] = None,
) -> None:
    """Envia uma mensagem de teste pelos canais disponiveis."""
    rt: RuntimeContext = ctx.obj
    import asyncio

    notifier, warnings = _notifier(rt)
    targets = channel or list(notifier.available)
    message = NotificationMessage(
        subject="[DealHunter] teste de notificação",
        body=(
            "Teste do DealHunter.\n"
            f"Horario: {rt.clock.now().isoformat()}\n"
            "Se voce recebeu esta mensagem, o canal esta operacional."
        ),
    )

    async def _send() -> list[tuple[str, bool, str | None]]:
        results: list[tuple[str, bool, str | None]] = []
        for target in targets:
            ok, error = await notifier.send(target, message)
            results.append((target, ok, error))
        return results

    results = asyncio.run(_send())

    if rt.json_output:
        emit_json(
            envelope(
                "notify.test",
                generated_at=rt.clock.now().isoformat(),
                results=[
                    {"channel": name, "ok": ok, "error": error} for name, ok, error in results
                ],
                warnings=warnings,
            )
        )
    else:
        for name, ok, error in results:
            if ok:
                rt.console.print(f"[green]{escape(name)}: enviado[/green]")
            else:
                rt.console.print(f"[red]{escape(name)}: falhou ({escape(error or '')})[/red]")
        for warning in warnings:
            rt.console.print(f"[yellow]! {escape(warning)}[/yellow]")

    if not all(ok for _, ok, _ in results):
        raise typer.Exit(code=int(ExitCode.ERROR))
