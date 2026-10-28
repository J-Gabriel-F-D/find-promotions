"""Renderização e serialização do agregado de avaliações."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich import box
from rich.markup import escape
from rich.panel import Panel

from dealhunter.application.dto import ReviewRow
from dealhunter.application.use_cases.reviews import ReviewReport
from dealhunter.cli.render import envelope
from dealhunter.runtime.container import RuntimeContext

DISCLAIMER = (
    "Agregado publicado pela fonte. Não é análise de sentimento nem de "
    "reclamações — isso exige a Fase 3 (IA opcional com salvaguardas)."
)


def _bar(value: int, total: int, *, unicode: bool, width: int = 20) -> str:
    if total <= 0:
        return ""
    filled = round(value / total * width)
    filled_char = "█" if unicode else "#"
    empty_char = "·" if unicode else "."
    return filled_char * filled + empty_char * (width - filled)


def review_source_payload(row: ReviewRow, *, now: datetime) -> dict[str, Any]:
    review = row.review
    return {
        "store": row.store_name,
        "source": review.source,
        "source_url": review.source_url,
        "rating": review.rating_avg,
        "count": review.rating_count,
        "distribution": {str(score): count for score, count in sorted(review.distribution.items())},
        "negative_share": review.negative_share,
        "collected_at": review.collected_at.isoformat() if review.collected_at else None,
        "last_verified_at": (
            review.last_verified_at.isoformat() if review.last_verified_at else None
        ),
        "confidence": review.confidence,
        "as_of": now.isoformat(timespec="seconds"),
    }


def reviews_payload(report: ReviewReport, *, now: datetime) -> dict[str, Any]:
    return envelope(
        "reviews",
        generated_at=now.isoformat(timespec="seconds"),
        product={"id": report.product_id, "title": report.product_title},
        sources=[review_source_payload(row, now=now) for row in report.rows],
        warnings=list(report.warnings) + [DISCLAIMER],
    )


def render_reviews(report: ReviewReport, rt: RuntimeContext) -> None:
    console = rt.console
    for warning in report.warnings:
        console.print(f"[yellow]{rt.glyphs.warn} {escape(warning)}[/yellow]")

    console.print(
        Panel.fit(escape(report.product_title), style="bold", box=box.ROUNDED, border_style="cyan")
    )
    if not report.rows:
        console.print("[bold]Nenhuma avaliação agregada foi coletada para este produto.[/bold]")
        return

    for row in report.rows:
        review = row.review
        rating = f"{review.rating_avg:.1f}".replace(".", ",")
        console.print(
            f"{rt.glyphs.star} [bold]{rating}/5[/bold] em "
            f"{review.rating_count} avaliações "
            f"[dim]({escape(row.store_name)} · {escape(review.source)})[/dim]"
        )
        for score in (5, 4, 3, 2, 1):
            count = review.distribution.get(score, 0)
            suffix = "★" if rt.unicode_enabled else " estrelas"
            bar = _bar(count, review.rating_count, unicode=rt.unicode_enabled)
            console.print(
                f"  {score}{suffix} [cyan]{bar}[/cyan] {count}",
                highlight=False,
            )
        if review.negative_share:
            console.print(
                f"  [yellow]1–2 estrelas: {review.negative_share * 100:.1f}% do total[/yellow]"
            )
        console.print(f"  [dim]{escape(review.source_url)}[/dim]")
        if review.collected_at is not None:
            console.print(
                f"  [dim]coletado em {review.collected_at.strftime('%d/%m/%Y %H:%M')} UTC[/dim]"
            )
        console.print()

    console.print(f"[dim]{DISCLAIMER}[/dim]")
