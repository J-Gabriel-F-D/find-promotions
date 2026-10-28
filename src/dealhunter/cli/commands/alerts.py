"""Comandos ``dealhunter alerts``."""

from __future__ import annotations

from typing import Annotated

import typer
from rich import box
from rich.markup import escape
from rich.table import Table

from dealhunter.adapters.storage.repository import SqliteRepository
from dealhunter.application.dto import QuerySpec
from dealhunter.application.intent import parse_query
from dealhunter.application.use_cases.alerts import create_alert
from dealhunter.cli.exit_codes import ExitCode
from dealhunter.cli.parsing import parse_money_option, parse_percent_option
from dealhunter.cli.render import emit_json, envelope
from dealhunter.cli.wiring import ensure_database, run_alerts_check
from dealhunter.runtime.container import RuntimeContext

app = typer.Typer(help="Cria e gerencia alertas de preço.", no_args_is_help=True)


def _rule_text(max_price_cents: int | None, min_discount_pct: float | None) -> str:
    from dealhunter.domain.value_objects.money import Money

    parts = []
    if max_price_cents is not None:
        parts.append(f"<= {Money(max_price_cents)}")
    if min_discount_pct is not None:
        parts.append(f">= {min_discount_pct:g}% desconto")
    return " ou ".join(parts)


@app.command("create")
def create(
    ctx: typer.Context,
    query: Annotated[str | None, typer.Argument(help="Busca em linguagem natural.")] = None,
    product: Annotated[str | None, typer.Option("--product", "-p")] = None,
    max_price: Annotated[str | None, typer.Option("--max-price", help="Preço-alvo.")] = None,
    discount: Annotated[
        str | None, typer.Option("--discount", help="Desconto mínimo (%%) vs média.")
    ] = None,
    channel: Annotated[
        list[str] | None, typer.Option("--channel", help="Canal (repetivel). Padrão: config.")
    ] = None,
    label: Annotated[str | None, typer.Option("--label", help="Nome do alerta.")] = None,
) -> None:
    """Cria um alerta de preço."""
    rt: RuntimeContext = ctx.obj
    ensure_database(rt)

    if not query and not product:
        raise typer.BadParameter("informe uma busca livre ou --product")

    try:
        spec = parse_query(query) if query else QuerySpec(product=product or "")
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    max_price_cents = parse_money_option(max_price, option="--max-price")
    min_discount = parse_percent_option(discount, option="--discount")
    channels = channel or list(rt.config.notifications.channels)

    try:
        alert_id = create_alert(
            SqliteRepository(rt.database),
            query=query or product or "",
            spec=spec,
            max_price_cents=max_price_cents,
            min_discount_pct=min_discount,
            channels=channels,
            label=label,
            now=rt.clock.now(),
            max_active=rt.config.monitor.max_active_alerts,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    if rt.json_output:
        emit_json(
            envelope(
                "alerts.create",
                generated_at=rt.clock.now().isoformat(),
                alert_id=alert_id,
                rule=_rule_text(max_price_cents, min_discount),
                channels=channels,
            )
        )
        return

    rt.console.print(f"[green]Alerta #{alert_id} criado.[/green]")
    rt.console.print(f"Regra: {_rule_text(max_price_cents, min_discount)}")
    rt.console.print(f"Canais: {', '.join(channels)}")
    rt.console.print(f"Verifique com: [bold]dealhunter alerts check {alert_id}[/bold]")


@app.command("list")
def list_alerts(ctx: typer.Context) -> None:
    """Lista os alertas cadastrados."""
    rt: RuntimeContext = ctx.obj
    ensure_database(rt)
    alerts = SqliteRepository(rt.database).list_alerts()

    if rt.json_output:
        emit_json(
            envelope(
                "alerts.list",
                generated_at=rt.clock.now().isoformat(),
                alerts=[
                    {
                        "id": alert.id,
                        "label": alert.label,
                        "query": alert.query,
                        "rule": _rule_text(alert.max_price_cents, alert.min_discount_pct),
                        "channels": list(alert.channels),
                        "active": alert.active,
                        "created_at": alert.created_at,
                        "last_checked_at": alert.last_checked_at,
                    }
                    for alert in alerts
                ],
            )
        )
        return

    if not alerts:
        rt.console.print("[dim]Nenhum alerta cadastrado.[/dim]")
        return

    table = Table(box=box.SIMPLE_HEAD, show_edge=False)
    table.add_column("ID", justify="right")
    table.add_column("Produto")
    table.add_column("Regra")
    table.add_column("Status")
    table.add_column("Ultima checagem", style="dim")
    for alert in alerts:
        status = "[green]ativo[/green]" if alert.active else "[yellow]pausado[/yellow]"
        table.add_row(
            str(alert.id),
            escape(alert.label),
            _rule_text(alert.max_price_cents, alert.min_discount_pct),
            status,
            alert.last_checked_at or "-",
        )
    rt.console.print(table)


@app.command("pause")
def pause(ctx: typer.Context, alert_id: Annotated[int, typer.Argument()]) -> None:
    """Pausa um alerta."""
    _set_active(ctx, alert_id, active=False)


@app.command("resume")
def resume(ctx: typer.Context, alert_id: Annotated[int, typer.Argument()]) -> None:
    """Reativa um alerta."""
    _set_active(ctx, alert_id, active=True)


def _set_active(ctx: typer.Context, alert_id: int, *, active: bool) -> None:
    rt: RuntimeContext = ctx.obj
    ensure_database(rt)
    changed = SqliteRepository(rt.database).set_alert_active(alert_id, active)

    if rt.json_output:
        emit_json(
            envelope(
                "alerts.set_active",
                generated_at=rt.clock.now().isoformat(),
                alert_id=alert_id,
                active=active,
                changed=changed,
            )
        )
        return

    if not changed:
        rt.error_console.print(f"[yellow]Alerta #{alert_id} não encontrado.[/yellow]")
        raise typer.Exit(code=int(ExitCode.NO_RESULTS))
    rt.console.print(f"[green]Alerta #{alert_id} {'reativado' if active else 'pausado'}.[/green]")


@app.command("delete")
def delete(ctx: typer.Context, alert_id: Annotated[int, typer.Argument()]) -> None:
    """Remove um alerta."""
    rt: RuntimeContext = ctx.obj
    ensure_database(rt)
    deleted = SqliteRepository(rt.database).delete_alert(alert_id)

    if rt.json_output:
        emit_json(
            envelope(
                "alerts.delete",
                generated_at=rt.clock.now().isoformat(),
                alert_id=alert_id,
                deleted=deleted,
            )
        )
        if not deleted:
            raise typer.Exit(code=int(ExitCode.NO_RESULTS))
        return

    if not deleted:
        rt.error_console.print(f"[yellow]Alerta #{alert_id} não encontrado.[/yellow]")
        raise typer.Exit(code=int(ExitCode.NO_RESULTS))
    rt.console.print(f"[green]Alerta #{alert_id} removido.[/green]")


@app.command("check")
def check(
    ctx: typer.Context,
    alert_id: Annotated[int | None, typer.Argument(help="ID do alerta (vazio = todos).")] = None,
    source: Annotated[list[str] | None, typer.Option("--source", "-s")] = None,
) -> None:
    """Executa a busca dos alertas ativos e notifica quem atingiu a regra."""
    rt: RuntimeContext = ctx.obj
    outcomes = run_alerts_check(rt, alert_id=alert_id, sources=source)

    if rt.json_output:
        emit_json(
            envelope(
                "alerts.check",
                generated_at=rt.clock.now().isoformat(),
                outcomes=[
                    {
                        "alert_id": outcome.alert_id,
                        "label": outcome.label,
                        "matched": outcome.matched,
                        "offer_id": outcome.offer_id,
                        "price_cents": outcome.price.cents if outcome.price else None,
                        "channels": [
                            {"channel": channel, "ok": ok, "error": error}
                            for channel, ok, error in outcome.channels_sent
                        ],
                        "note": outcome.note,
                    }
                    for outcome in outcomes
                ],
            )
        )
        return

    if not outcomes:
        rt.console.print("[dim]Nenhum alerta ativo.[/dim]")
        return

    for outcome in outcomes:
        if not outcome.matched:
            rt.console.print(
                f"[dim]#{outcome.alert_id} {escape(outcome.label)}: {escape(outcome.note)}[/dim]"
            )
            continue
        rt.console.print(
            f"[bold green]#{outcome.alert_id}[/bold green] {escape(outcome.label)}: "
            f"{outcome.price} — {escape(outcome.note)}"
        )
        for channel, ok, error in outcome.channels_sent:
            mark = "[green]ok[/green]" if ok else f"[red]falhou ({escape(error or '')})[/red]"
            rt.console.print(f"  {escape(channel)}: {mark}")
