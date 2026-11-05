"""Segurança de textos de avaliação: markup, ANSI e PII de autor."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from rich.console import Console

from dealhunter.application.dto import ReviewRow
from dealhunter.application.use_cases.reviews import ReviewAnalysisRow, ReviewReport
from dealhunter.cli.render.reviews import render_reviews
from dealhunter.cli.ui.glyphs import glyphs_for
from dealhunter.domain.models import ReviewSummary, ReviewText
from dealhunter.services.reviews import analyze


def _report(body: str, title: str = "") -> ReviewReport:
    text = ReviewText(
        product_id="prd_a",
        store_id="str_a",
        source="feed",
        source_url="https://loja.example/feed",
        rating=1,
        body=body,
        title=title,
        reviewed_at=datetime(2026, 3, 1, 12, tzinfo=UTC),
        collected_at=datetime(2026, 3, 15, 12, tzinfo=UTC),
    )
    summary = ReviewSummary(
        product_id="prd_a",
        store_id="str_a",
        rating_avg=1.0,
        rating_count=1,
        source="feed",
        source_url="https://loja.example/feed",
        distribution={1: 1},
        collected_at=datetime(2026, 3, 15, 12, tzinfo=UTC),
        texts=(text,),
    )
    row = ReviewRow(
        review=summary,
        product_title="Produto",
        store_name="[red]Loja[/red]",
    )
    analysis = analyze(summary.texts, include_text=True)
    return ReviewReport(
        product_id="prd_a",
        product_title="Produto",
        rows=(row,),
        analyses=(
            ReviewAnalysisRow(
                review_id=summary.id,
                store_name=row.store_name,
                source=summary.source,
                analysis=analysis,
            ),
        ),
    )


def _render(report: ReviewReport) -> str:
    output = __import__("io").StringIO()
    console = Console(
        file=output,
        no_color=True,
        force_terminal=False,
        width=200,
        highlight=False,
    )
    render_reviews(
        report,
        SimpleNamespace(
            console=console,
            glyphs=glyphs_for(True),
            unicode_enabled=True,
        ),
        include_text=True,
        limit=10,
    )
    return output.getvalue()


def test_markup_e_html_do_texto_sao_escapados() -> None:
    output = _render(
        _report(
            "[bold red]CLIQUE AQUI[/bold red] <script>alert(1)</script>",
            title="[link=https://evil.example]Título[/link]",
        )
    )
    assert "[bold red]CLIQUE AQUI[/bold red]" in output
    assert "<script>alert(1)</script>" in output
    assert "\x1b[" not in output


def test_texto_nao_injeta_quebra_de_terminal() -> None:
    output = _render(_report("linha1\nlinha2\rlinha3\x07"))
    assert "\x07" not in output


def test_autor_nao_e_modelado_nem_renderizado() -> None:
    text = ReviewText(
        product_id="prd_a",
        store_id="str_a",
        source="feed",
        source_url="https://loja.example/feed",
        rating=5,
        body="Ótimo.",
        collected_at=datetime(2026, 3, 15, 12, tzinfo=UTC),
    )
    assert not hasattr(text, "author")
    assert "author" not in text.__dataclass_fields__
