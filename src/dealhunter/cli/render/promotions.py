"""Renderização e serialização de promoções."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich import box
from rich.markup import escape
from rich.table import Table

from dealhunter.application.dto import PromotionRow
from dealhunter.application.use_cases.promotions import PromotionReport
from dealhunter.cli.render import envelope
from dealhunter.domain.models import PromotionState
from dealhunter.runtime.container import RuntimeContext
from dealhunter.services import promotions as promotion_rules

STATE_LABELS: dict[PromotionState, str] = {
    "active": "ativa",
    "scheduled": "agendada",
    "expired": "encerrada",
    "unknown": "sem janela",
}

STATE_STYLES = {
    "active": "green",
    "scheduled": "yellow",
    "expired": "dim",
    "unknown": "yellow",
}

KIND_LABELS = {
    "flash": "relâmpago",
    "regular": "regular",
    "clearance": "liquidação",
}


def promotion_payload(row: PromotionRow, *, now: datetime) -> dict[str, Any]:
    promotion = row.promotion
    return {
        "id": promotion.id,
        "kind": promotion.kind,
        "label": promotion.label,
        "state": promotion.state_at(now),
        "urgency": promotion_rules.urgency(promotion, now),
        "remaining": promotion_rules.remaining_label(promotion, now),
        "starts_at": promotion.starts_at.isoformat() if promotion.starts_at else None,
        "ends_at": promotion.ends_at.isoformat() if promotion.ends_at else None,
        "offer_id": row.offer_id,
        "product_id": row.product_id,
        "product_title": row.product_title,
        "store": row.store_name,
        "url": row.offer_url,
        "source": promotion.source,
        "source_url": promotion.source_url,
        "collected_at": (promotion.collected_at.isoformat() if promotion.collected_at else None),
        "confidence": promotion.confidence,
    }


def promotions_payload(report: PromotionReport) -> dict[str, Any]:
    return envelope(
        "promotions",
        generated_at=report.now.isoformat(timespec="seconds"),
        include_expired=report.include_expired,
        count=len(report.rows),
        promotions=[promotion_payload(row, now=report.now) for row in report.rows],
        warnings=list(report.warnings),
    )


def render_promotions(report: PromotionReport, rt: RuntimeContext) -> None:
    console = rt.console
    for warning in report.warnings:
        console.print(f"[yellow]{rt.glyphs.warn} {escape(warning)}[/yellow]")

    if not report.rows:
        console.print("[bold]Nenhuma promoção registrada com os filtros atuais.[/bold]")
        console.print("[dim]Rode uma busca em fontes que declarem janelas promocionais.[/dim]")
        return

    table = Table(box=box.SIMPLE, header_style="bold", pad_edge=False)
    table.add_column("Tipo")
    table.add_column("Produto")
    table.add_column("Loja")
    table.add_column("Janela")
    table.add_column("Situação")

    for row in report.rows:
        promotion = row.promotion
        state = promotion.state_at(report.now)
        style = STATE_STYLES[state]
        window = promotion_rules.remaining_label(promotion, report.now) or "sem prazo"
        table.add_row(
            escape(KIND_LABELS.get(promotion.kind, promotion.kind)),
            escape(row.product_title),
            escape(row.store_name),
            window,
            f"[{style}]{STATE_LABELS[state]}[/{style}]",
        )
    console.print(table)
    console.print(
        "[dim]Janela declarada pela fonte. Urgência é apenas um sinal de tempo; "
        "não indica confiabilidade nem desconto real.[/dim]"
    )
