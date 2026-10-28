"""Renderizacao e serializacao dos resultados de busca."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from rich import box
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from dealhunter.application.dto import SearchReport
from dealhunter.cli.render import envelope
from dealhunter.domain.models import CouponEvaluation, OfferView
from dealhunter.runtime.container import RuntimeContext
from dealhunter.services import coupons as coupon_rules
from dealhunter.services import promotions as promotion_rules

DISCOUNT_LABELS = {
    "likely_real": ("provavelmente real", "green"),
    "normal": ("normal", "yellow"),
    "suspicious": ("suspeito", "red"),
    "insufficient_evidence": ("sem evidência suficiente", "dim"),
}

FLAG_LABELS = {
    "frete_nao_informado": "frete não informado",
    "historico_insuficiente": "histórico insuficiente",
    "reputacao_desconhecida": "reputação desconhecida",
    "cupom_nao_validado": "cupom não validado na loja",
    "promocao_sem_janela": "promoção sem janela declarada",
}


def _now(report: SearchReport) -> datetime:
    if report.started_at:
        parsed = datetime.fromisoformat(report.started_at)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return datetime.now(UTC)


def search_payload(report: SearchReport) -> dict[str, Any]:
    now = _now(report)
    return envelope(
        "search",
        generated_at=report.started_at,
        query={"raw": report.spec.raw, "spec": report.spec.model_dump(mode="json")},
        sources=[
            {
                "id": status.source_id,
                "label": status.label,
                "status": status.status,
                "items": status.items,
                "discarded": status.discarded,
                "duration_ms": status.duration_ms,
                "error": status.error,
            }
            for status in report.sources
        ],
        picks=report.picks,
        stats={
            "collected": report.collected,
            "eligible": len(report.views),
            "discarded": report.discarded,
            "discard_reasons": report.discard_reasons,
            "duration_ms": report.duration_ms,
        },
        results=[offer_payload(view, now=now) for view in report.views],
        warnings=list(report.warnings),
    )


def coupon_payload(evaluation: CouponEvaluation, *, now: datetime) -> dict[str, Any]:
    coupon = evaluation.coupon
    return {
        "code": coupon.code,
        "kind": coupon.kind,
        "value": coupon.value,
        "benefit": coupon_rules.describe_benefit(coupon),
        "min_purchase_cents": coupon.min_purchase.cents if coupon.min_purchase else None,
        "max_discount_cents": coupon.max_discount.cents if coupon.max_discount else None,
        "valid_from": coupon.valid_from.isoformat() if coupon.valid_from else None,
        "valid_until": coupon.valid_until.isoformat() if coupon.valid_until else None,
        "state": coupon.state_at(now),
        "validation": coupon.validation,
        "last_verified_at": (
            coupon.last_verified_at.isoformat() if coupon.last_verified_at else None
        ),
        "applicable": evaluation.applicable,
        "reason": evaluation.reason,
        "estimated_discount_cents": evaluation.discount.cents,
        "estimated_final_price_cents": evaluation.final_price.cents,
        "estimate": evaluation.estimate,
        "source": coupon.source,
        "source_url": coupon.source_url,
        "collected_at": coupon.collected_at.isoformat() if coupon.collected_at else None,
        "confidence": coupon.confidence,
    }


def offer_payload(view: OfferView, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    offer, product, stats = view.offer, view.product, view.stats
    best = view.best_coupon
    return {
        "offer_id": offer.id,
        "product_id": product.id,
        "title": product.title,
        "brand": product.brand,
        "storage_gb": product.storage_gb,
        "ram_gb": product.ram_gb,
        "identity": product.identity_kind,
        "store": {"name": view.store.name, "domain": view.store.domain},
        "seller": (
            {"name": view.seller.name, "rating": view.seller.rating} if view.seller else None
        ),
        "price_cents": offer.price.cents,
        "list_price_cents": offer.list_price.cents if offer.list_price else None,
        "shipping_cents": offer.shipping.cents if offer.shipping is not None else None,
        "final_price_cents": offer.final_price.cents,
        "estimated_final_price_with_coupon_cents": best.final_price.cents if best else None,
        "currency": offer.price.currency,
        "coupon": offer.coupon_code,
        "coupons": [coupon_payload(item, now=now) for item in view.coupons],
        "best_coupon": coupon_payload(best, now=now) if best else None,
        "promotion": (
            {
                "kind": view.promotion.kind,
                "label": view.promotion.label,
                "starts_at": (
                    view.promotion.starts_at.isoformat() if view.promotion.starts_at else None
                ),
                "ends_at": (view.promotion.ends_at.isoformat() if view.promotion.ends_at else None),
                "state": view.promotion.state_at(now),
                "urgency": promotion_rules.urgency(view.promotion, now),
                "remaining": promotion_rules.remaining_label(view.promotion, now),
                "source": view.promotion.source,
                "source_url": view.promotion.source_url,
                "collected_at": (
                    view.promotion.collected_at.isoformat() if view.promotion.collected_at else None
                ),
                "confidence": view.promotion.confidence,
            }
            if view.promotion
            else None
        ),
        "reviews": (
            {
                "rating": view.reviews.rating_avg,
                "count": view.reviews.rating_count,
                "distribution": {
                    str(score): count for score, count in sorted(view.reviews.distribution.items())
                },
                "negative_share": view.reviews.negative_share,
                "source": view.reviews.source,
                "source_url": view.reviews.source_url,
                "collected_at": (
                    view.reviews.collected_at.isoformat() if view.reviews.collected_at else None
                ),
                "confidence": view.reviews.confidence,
            }
            if view.reviews
            else None
        ),
        "deal_score": view.deal_score,
        "score_breakdown": view.score_breakdown,
        "discount": {
            "classification": view.discount.classification,
            "evidence": view.discount.evidence,
        },
        "history": (
            {
                "samples": stats.samples,
                "days_covered": stats.days_covered,
                "average_cents": stats.average.cents,
                "median_cents": stats.median.cents,
                "min_cents": stats.minimum.cents,
                "max_cents": stats.maximum.cents,
                "position_pct": stats.position_pct,
                "sufficient": stats.sufficient_history,
                "discount_vs_average_pct": stats.discount_vs_average(),
            }
            if stats
            else None
        ),
        "flags": list(view.flags),
        "url": offer.url,
        "source": offer.source,
        "collected_at": offer.collected_at.isoformat() if offer.collected_at else None,
        "confidence": offer.confidence,
    }


def _source_lines(report: SearchReport, rt: RuntimeContext) -> Table:
    glyphs = rt.glyphs
    table = Table(box=None, show_header=False, pad_edge=False, expand=False, padding=(0, 1))
    table.add_column("status", width=2)
    table.add_column("fonte")
    table.add_column("detalhe", style="dim")

    for status in report.sources:
        if status.status == "ok":
            icon, style = glyphs.ok, "green"
            detail = f"{status.items} oferta(s) em {status.duration_ms} ms"
        elif status.status == "empty":
            icon, style = glyphs.idle, "yellow"
            detail = "nenhuma oferta"
        elif status.status == "timeout":
            icon, style = glyphs.fail, "red"
            detail = "tempo limite excedido"
        else:
            icon, style = glyphs.fail, "red"
            detail = status.error or status.status

        table.add_row(f"[{style}]{icon}[/{style}]", escape(status.label), escape(detail))
    return table


def _offer_card(view: OfferView, rt: RuntimeContext, badges: list[str], now: datetime) -> Panel:
    glyphs = rt.glyphs
    offer, stats = view.offer, view.stats
    title = f"[bold]{escape(view.product.title)}[/bold]"

    lines = [title]
    price_line = f"[bold green]{offer.price}[/bold green]"
    if offer.list_price and offer.list_price > offer.price:
        price_line += f"  [dim]de {offer.list_price}[/dim]"
    lines.append(price_line)

    store_line = f"{glyphs.store} {escape(view.store.name)}"
    if view.seller and view.seller.rating is not None:
        store_line += (
            f"  {glyphs.star} {view.seller.rating:.1f}/5 ({escape(view.seller.name or '')})"
        )
    lines.append(store_line)

    if offer.shipping is None:
        lines.append(f"{glyphs.truck} frete não informado")
    elif offer.shipping.cents == 0:
        lines.append(f"{glyphs.truck} [green]frete grátis[/green]")
    else:
        lines.append(f"{glyphs.truck} {offer.shipping}")

    if stats:
        window = f"{stats.days_covered}d " if stats.days_covered else ""
        unit = "amostra" if stats.samples == 1 else "amostras"
        lines.append(
            f"{glyphs.chart} média {window}{stats.average} | "
            f"posição {stats.position_pct:.0f}% | {stats.samples} {unit}"
        )
        if stats.sufficient_history:
            lines.append(
                f"{glyphs.fire} [bold]{stats.discount_vs_average()}%[/bold] abaixo da média"
            )
    else:
        lines.append(f"{glyphs.chart} sem histórico coletado")

    label, color = DISCOUNT_LABELS[view.discount.classification]
    lines.append(
        f"Desconto: [{color}]{label}[/{color}] [dim]({escape(view.discount.evidence)})[/dim]"
    )

    if view.promotion is not None and view.promotion.state_at(now) == "active":
        promo_label = view.promotion.label or "promoção ativa"
        remaining = promotion_rules.remaining_label(view.promotion, now)
        suffix = f" [dim]· {remaining}[/dim]" if remaining else ""
        lines.append(f"{glyphs.fire} [bold yellow]{escape(promo_label)}[/bold yellow]{suffix}")
        lines.append("[dim]janela declarada pela fonte; urgência não indica confiabilidade[/dim]")
    elif view.promotion is not None:
        state = view.promotion.state_at(now)
        if state == "expired":
            lines.append(f"[dim]{glyphs.clock} promoção declarada já encerrada[/dim]")
        elif state == "scheduled":
            lines.append(f"[dim]{glyphs.clock} promoção agendada (ainda não vigente)[/dim]")

    if view.best_coupon is not None:
        best = view.best_coupon
        lines.append(
            f"{glyphs.tag} cupom [bold]{escape(best.coupon.code)}[/bold] "
            f"({coupon_rules.describe_benefit(best.coupon)}) "
            f"{glyphs.arrow} estimado [bold green]{best.final_price}[/bold green] "
            "[dim](não validado na loja)[/dim]"
        )
    elif view.coupons:
        first = view.coupons[0]
        lines.append(
            f"{glyphs.tag} cupom [bold]{escape(first.coupon.code)}[/bold]: "
            f"[dim]{escape(first.reason)}[/dim]"
        )

    if view.reviews is not None:
        rating = f"{view.reviews.rating_avg:.1f}".replace(".", ",")
        lines.append(
            f"{glyphs.star} {rating}/5 em {view.reviews.rating_count} avaliações "
            f"[dim](agregado da fonte)[/dim]"
        )

    lines.append(
        f"{glyphs.target} oportunidade [bold]{view.deal_score:.0f}/100[/bold] "
        "[dim](preço/desconto/frete/histórico/avaliações/urgência; "
        "não é score de confiança)[/dim]"
    )

    flags = [FLAG_LABELS.get(flag, flag) for flag in view.flags]
    if flags:
        lines.append(f"[yellow]{glyphs.warn} {'; '.join(flags)}[/yellow]")

    lines.append(f"[dim]{escape(offer.url)}[/dim]")

    heading = " ".join(badges) if badges else "OFERTA"
    border = "cyan" if badges else "bright_black"
    return Panel(
        "\n".join(lines),
        title=heading,
        title_align="left",
        border_style=border,
        box=box.ROUNDED,
        padding=(0, 1),
    )


def render_search(report: SearchReport, rt: RuntimeContext) -> None:
    console = rt.console
    glyphs = rt.glyphs

    for warning in report.warnings:
        console.print(f"[yellow]{glyphs.warn} {escape(warning)}[/yellow]")

    console.print(
        Panel.fit(
            "[bold cyan]DEALHUNTER[/bold cyan]\n[dim]Intelligent Deal Search Engine[/dim]",
            box=box.ROUNDED,
            border_style="cyan",
        )
    )

    summary = "\n".join(report.spec.summary()) or f"Busca livre: {escape(report.spec.raw)}"
    console.print(summary, style="bold")
    console.print(_source_lines(report, rt))
    console.print(
        f"[dim]{report.collected} coletadas | {len(report.views)} válidas | "
        f"{report.discarded} descartadas | {report.duration_ms} ms[/dim]"
    )

    if not report.views:
        console.print(
            "\n[bold]Nenhuma oferta válida encontrada.[/bold] "
            "Ajuste os filtros ou habilite outras fontes."
        )
        if report.discard_reasons:
            reasons = ", ".join(f"{key}={value}" for key, value in report.discard_reasons.items())
            console.print(f"[dim]motivos de descarte: {reasons}[/dim]")
        return

    console.print()
    now = _now(report)
    for index, view in enumerate(report.views, start=1):
        badges: list[str] = []
        if report.picks.get("best") == view.offer.id:
            badges.append(f"{glyphs.trophy} MELHOR OFERTA")
        if report.picks.get("cheapest") == view.offer.id:
            badges.append(f"{glyphs.money} MENOR PREÇO")
        if report.picks.get("flash") == view.offer.id:
            badges.append(f"{glyphs.fire} RELÂMPAGO")
        if not badges:
            badges.append(f"#{index}")
        console.print(_offer_card(view, rt, badges, now))
