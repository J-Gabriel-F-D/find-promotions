"""Renderização e serialização de avaliações e da análise dos textos."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich import box
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel

from dealhunter.application.dto import ReviewRow
from dealhunter.application.use_cases.reviews import ReviewReport
from dealhunter.cli.render import envelope
from dealhunter.domain.models import ReviewText
from dealhunter.runtime.container import RuntimeContext
from dealhunter.services.reviews import (
    REVIEW_DISCLAIMER,
    ComplaintCategory,
    ReviewTextAnalysis,
)

DISCLAIMER = REVIEW_DISCLAIMER


def _bar(value: int, total: int, *, unicode: bool, width: int = 20) -> str:
    if total <= 0:
        return ""
    filled = round(value / total * width)
    filled_char = "█" if unicode else "#"
    empty_char = "░" if unicode else "."
    return filled_char * filled + empty_char * (width - filled)


def text_payload(text: ReviewText) -> dict[str, Any]:
    return {
        "id": text.id,
        "rating": text.rating,
        "title": text.title,
        "body": text.body,
        "reviewed_at": text.reviewed_at.isoformat() if text.reviewed_at else None,
        "source": text.source,
        "source_url": text.source_url,
        "collected_at": text.collected_at.isoformat() if text.collected_at else None,
        "last_verified_at": (text.last_verified_at.isoformat() if text.last_verified_at else None),
        "confidence": text.confidence,
    }


def _complaint_payload(category: ComplaintCategory) -> dict[str, Any]:
    return {
        "code": category.code,
        "label": category.label,
        "mentions": category.mentions,
        "evidence": [
            {
                "review_id": item.review_id,
                "rating": item.rating,
                "matched_terms": list(item.matched_terms),
                "snippet": item.snippet,
            }
            for item in category.evidence
        ],
    }


def analysis_payload(analysis: ReviewTextAnalysis) -> dict[str, Any]:
    return {
        "sample_size": analysis.sample_size,
        "with_text": analysis.with_text,
        "sentiment_counts": dict(analysis.sentiment_counts),
        "sentiment_share": dict(analysis.sentiment_share),
        "complaints": [_complaint_payload(item) for item in analysis.complaints],
        "analysis_confidence": analysis.analysis_confidence,
        "limitations": list(analysis.limitations),
        "rules_version": analysis.rules_version,
        "disclaimer": analysis.disclaimer,
    }


def review_source_payload(
    row: ReviewRow,
    *,
    now: datetime,
    analysis: ReviewTextAnalysis | None = None,
    include_text: bool = False,
) -> dict[str, Any]:
    review = row.review
    payload: dict[str, Any] = {
        "store": row.store_name,
        "source": review.source,
        "source_url": review.source_url,
        "rating": review.rating_avg,
        "count": review.rating_count,
        "distribution": {str(score): count for score, count in sorted(review.distribution.items())},
        "negative_share": review.negative_share,
        "text_count": len(review.texts),
        "analysis": analysis_payload(analysis) if analysis is not None else None,
        "collected_at": review.collected_at.isoformat() if review.collected_at else None,
        "last_verified_at": (
            review.last_verified_at.isoformat() if review.last_verified_at else None
        ),
        "confidence": review.confidence,
        "as_of": now.isoformat(timespec="seconds"),
    }
    if include_text:
        payload["texts"] = [text_payload(text) for text in review.texts]
    return payload


def reviews_payload(
    report: ReviewReport, *, now: datetime, include_text: bool = False
) -> dict[str, Any]:
    analyses = {item.review_id: item.analysis for item in report.analyses}
    return envelope(
        "reviews",
        generated_at=now.isoformat(timespec="seconds"),
        product={"id": report.product_id, "title": report.product_title},
        sources=[
            review_source_payload(
                row,
                now=now,
                analysis=analyses.get(row.review.id),
                include_text=include_text,
            )
            for row in report.rows
        ],
        warnings=list(report.warnings) + [REVIEW_DISCLAIMER],
    )


def _render_analysis(analysis: ReviewTextAnalysis, *, console: Console) -> None:
    if analysis.sample_size <= 0:
        console.print(
            "  [dim]Nenhum texto individual publicado pela fonte; "
            "a análise de reclamações não pôde ser feita.[/dim]"
        )
        return

    counts = analysis.sentiment_counts
    console.print(
        f"  [bold]Textos analisados:[/bold] {analysis.sample_size} "
        f"(com texto: {analysis.with_text}; confiança {analysis.analysis_confidence:.2f})"
    )
    console.print(
        "  [bold]Sentimento pela nota:[/bold] "
        f"positivo {counts.get('positive', 0)} | "
        f"neutro {counts.get('neutral', 0)} | "
        f"negativo {counts.get('negative', 0)}"
    )
    if analysis.complaints:
        rendered = ", ".join(
            f"{escape(item.label)} ({item.mentions})" for item in analysis.complaints
        )
        console.print(f"  [bold]Reclamações mencionadas:[/bold] {rendered}")
    else:
        console.print("  [bold]Reclamações mencionadas:[/bold] nenhuma nos textos da amostra")
    for limitation in analysis.limitations:
        console.print(f"  [dim]{escape(limitation)}[/dim]")


def _render_texts(row: ReviewRow, *, limit: int, console: Console) -> None:
    if not row.review.texts:
        console.print("  [dim]Nenhum texto individual disponível para esta loja.[/dim]")
        return
    for text in row.review.texts[:limit]:
        title = f"{text.title} — " if text.title else ""
        when = (
            text.reviewed_at.strftime("%d/%m/%Y")
            if text.reviewed_at is not None
            else "data não informada"
        )
        console.print(
            f"    [bold]{escape(title)}{text.rating}/5[/bold] [dim]({when})[/dim]",
            highlight=False,
        )
        console.print(f"    {escape(text.body)}", highlight=False)


def render_reviews(
    report: ReviewReport,
    rt: RuntimeContext,
    *,
    include_text: bool = False,
    limit: int = 20,
) -> None:
    console = rt.console
    for warning in report.warnings:
        console.print(f"[yellow]{rt.glyphs.warn} {escape(warning)}[/yellow]")

    console.print(
        Panel.fit(escape(report.product_title), style="bold", box=box.ROUNDED, border_style="cyan")
    )
    if not report.rows:
        console.print("[bold]Nenhuma avaliação agregada foi coletada para este produto.[/bold]")
        return

    analyses = {item.review_id: item.analysis for item in report.analyses}
    for row in report.rows:
        review = row.review
        rating = f"{review.rating_avg:.1f}".replace(".", ",")
        console.print(
            f"{rt.glyphs.star} [bold]{rating}/5[/bold] em "
            f"{review.rating_count} avaliações "
            f"[dim]({escape(row.store_name)} {rt.glyphs.idle} {escape(review.source)})[/dim]"
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
        analysis = analyses.get(review.id)
        if analysis is not None:
            _render_analysis(analysis, console=console)
        if include_text:
            _render_texts(row, limit=limit, console=console)
        console.print(f"  [dim]{escape(review.source_url)}[/dim]")
        if review.collected_at is not None:
            console.print(
                f"  [dim]coletado em {review.collected_at.strftime('%d/%m/%Y %H:%M')} UTC[/dim]"
            )
        console.print()

    console.print(f"[dim]{REVIEW_DISCLAIMER}[/dim]")
