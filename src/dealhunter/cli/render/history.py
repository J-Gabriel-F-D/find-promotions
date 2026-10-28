"""Renderizacao do comando ``history``."""

from __future__ import annotations

from typing import Any

from rich import box
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from dealhunter.application.dto import HistoryReport
from dealhunter.cli.render import envelope
from dealhunter.domain.value_objects.money import Money
from dealhunter.runtime.container import RuntimeContext


def history_payload(report: HistoryReport) -> dict[str, Any]:
    stats = report.stats
    return envelope(
        "history",
        generated_at=report.points[-1].collected_at if report.points else "",
        product={"id": report.product_id, "title": report.product_title},
        days=report.days,
        stats=(
            {
                "samples": stats.samples,
                "days_covered": stats.days_covered,
                "minimum_cents": stats.minimum.cents,
                "maximum_cents": stats.maximum.cents,
                "average_cents": stats.average.cents,
                "median_cents": stats.median.cents,
                "p10_cents": stats.p10.cents,
                "p90_cents": stats.p90.cents,
                "current_cents": stats.current.cents,
                "position_pct": stats.position_pct,
                "sufficient": stats.sufficient_history,
            }
            if stats
            else None
        ),
        points=[
            {
                "collected_at": point.collected_at,
                "price_cents": point.price.cents,
                "source": point.source,
            }
            for point in report.points
        ],
        offers=[
            {
                "offer_id": offer.offer_id,
                "store": offer.store_name,
                "seller": offer.seller_name,
                "price_cents": offer.price_cents,
                "shipping_cents": offer.shipping_cents,
                "collected_at": offer.collected_at,
                "source": offer.source,
                "url": offer.url,
                "confidence": offer.confidence,
            }
            for offer in report.offers
        ],
        warnings=list(report.warnings),
    )


def render_history(report: HistoryReport, rt: RuntimeContext) -> None:
    console = rt.console
    glyphs = rt.glyphs

    for warning in report.warnings:
        console.print(f"[yellow]{glyphs.warn} {escape(warning)}[/yellow]")

    console.print(
        Panel.fit(
            f"[bold]{escape(report.product_title)}[/bold]\n[dim]janela de {report.days} dias[/dim]",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )

    stats = report.stats
    if stats is None:
        console.print("[yellow]Nenhuma amostra de preço na janela.[/yellow]")
        return

    table = Table(box=box.SIMPLE_HEAD, show_edge=False)
    table.add_column("Metrica", style="bold")
    table.add_column("Valor", justify="right")
    table.add_row("Amostras", str(stats.samples))
    table.add_row("Cobertura", f"{stats.days_covered} dias")
    table.add_row("Mínimo", str(stats.minimum))
    table.add_row("P10 / P25", f"{stats.p10} / {stats.p25}")
    table.add_row("Mediana", str(stats.median))
    table.add_row("Média", str(stats.average))
    table.add_row("P75 / P90", f"{stats.p75} / {stats.p90}")
    table.add_row("Máximo", str(stats.maximum))
    table.add_row("Preço atual", str(stats.current))
    table.add_row("Posição no histórico", f"{stats.position_pct:.0f}%")
    table.add_row("Desconto vs média", f"{stats.discount_vs_average()}%")
    if not stats.sufficient_history:
        table.add_row("[yellow]Histórico[/yellow]", "[yellow]insuficiente para conclusão[/yellow]")
    console.print(table)

    if report.points:
        points = Table(box=box.SIMPLE_HEAD, show_edge=False)
        points.add_column("Quando")
        points.add_column("Preço", justify="right")
        points.add_column("Fonte", style="dim")
        for point in report.points[-15:]:
            points.add_row(point.collected_at, str(point.price), escape(point.source))
        console.print(points)

    if report.offers:
        offers = Table(box=box.SIMPLE_HEAD, show_edge=False)
        offers.add_column("Loja")
        offers.add_column("Preço", justify="right")
        offers.add_column("Frete", justify="right")
        offers.add_column("Verificado")
        for offer in report.offers:
            shipping = (
                "gratis"
                if offer.shipping_cents == 0
                else (
                    str(Money(offer.shipping_cents, offer.currency))
                    if offer.shipping_cents is not None
                    else "n/d"
                )
            )
            offers.add_row(
                escape(offer.store_name),
                str(Money(offer.price_cents, offer.currency)),
                shipping,
                offer.collected_at,
            )
        console.print(offers)
