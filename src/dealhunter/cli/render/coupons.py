"""Renderização e serialização de cupons."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich import box
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from dealhunter.application.dto import CouponCheck, CouponRow
from dealhunter.cli.render import envelope
from dealhunter.domain.value_objects.money import Money
from dealhunter.runtime.container import RuntimeContext
from dealhunter.services.coupons import KIND_LABELS, STATE_LABELS, describe_benefit

STATE_STYLES = {
    "active": "green",
    "scheduled": "yellow",
    "expired": "dim",
    "unknown": "yellow",
}

VALIDATION_NOTE = (
    "Cupons são declarações das fontes: nenhum foi validado na loja. "
    "Confirme o código no carrinho antes de comprar."
)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def coupon_row_payload(row: CouponRow, *, now: datetime) -> dict[str, Any]:
    coupon = row.coupon
    return {
        "id": coupon.id,
        "code": coupon.code,
        "kind": coupon.kind,
        "value": coupon.value,
        "benefit": describe_benefit(coupon),
        "min_purchase_cents": coupon.min_purchase.cents if coupon.min_purchase else None,
        "max_discount_cents": coupon.max_discount.cents if coupon.max_discount else None,
        "valid_from": _iso(coupon.valid_from),
        "valid_until": _iso(coupon.valid_until),
        "state": coupon.state_at(now),
        "validation": coupon.validation,
        "last_verified_at": _iso(coupon.last_verified_at),
        "store": {"name": row.store_name, "domain": row.store_domain},
        "source": coupon.source,
        "source_url": coupon.source_url,
        "collected_at": _iso(coupon.collected_at),
        "confidence": coupon.confidence,
    }


def coupons_payload(rows: tuple[CouponRow, ...], *, now: datetime) -> dict[str, Any]:
    return envelope(
        "coupons.list",
        generated_at=now.isoformat(timespec="seconds"),
        count=len(rows),
        coupons=[coupon_row_payload(row, now=now) for row in rows],
        warnings=[VALIDATION_NOTE],
    )


def check_payload(
    outcomes: tuple[CouponCheck, ...], *, now: datetime, price: Money, shipping: Money | None
) -> dict[str, Any]:
    return envelope(
        "coupons.check",
        generated_at=now.isoformat(timespec="seconds"),
        price_cents=price.cents,
        shipping_cents=shipping.cents if shipping is not None else None,
        currency=price.currency,
        results=[
            {
                "coupon": coupon_row_payload(
                    CouponRow(item.coupon, item.store_name, item.store_domain), now=now
                ),
                "applicable": item.evaluation.applicable,
                "reason": item.evaluation.reason,
                "estimated_discount_cents": item.evaluation.discount.cents,
                "estimated_final_price_cents": item.evaluation.final_price.cents,
                "estimate": item.evaluation.estimate,
                "validation_method": "local_rules",
            }
            for item in outcomes
        ],
        warnings=[VALIDATION_NOTE],
    )


def render_coupons(rows: tuple[CouponRow, ...], rt: RuntimeContext, *, now: datetime) -> None:
    console = rt.console
    if not rows:
        console.print("[bold]Nenhum cupom coletado.[/bold]")
        console.print("[dim]Rode uma busca em fontes que declarem cupons (feed ou fixture).[/dim]")
        return

    table = Table(box=box.SIMPLE, header_style="bold", pad_edge=False)
    table.add_column("Código")
    table.add_column("Loja")
    table.add_column("Benefício")
    table.add_column("Mínimo", justify="right")
    table.add_column("Validade")
    table.add_column("Situação")

    for row in rows:
        coupon = row.coupon
        state = coupon.state_at(now)
        style = STATE_STYLES[state]
        table.add_row(
            f"[bold]{escape(coupon.code)}[/bold]",
            escape(row.store_name),
            escape(describe_benefit(coupon)),
            coupon.min_purchase.format(symbol=False) if coupon.min_purchase else "-",
            coupon.valid_until.strftime("%d/%m/%Y") if coupon.valid_until else "-",
            f"[{style}]{STATE_LABELS[state]}[/{style}]",
        )
    console.print(table)
    console.print(f"[dim]{VALIDATION_NOTE}[/dim]")
    console.print("[dim]Use 'dealhunter coupons check CODIGO --price VALOR' para simular.[/dim]")


def render_coupon_check(
    outcomes: tuple[CouponCheck, ...],
    rt: RuntimeContext,
    *,
    now: datetime,
    code: str,
    price: Money,
    shipping: Money | None,
) -> None:
    console = rt.console
    if not outcomes:
        console.print(f"[yellow]Cupom não encontrado: {escape(code)}[/yellow]")
        console.print("[dim]Liste os cupons conhecidos com 'dealhunter coupons list'.[/dim]")
        return

    for item in outcomes:
        coupon = item.coupon
        state = coupon.state_at(now)
        style = STATE_STYLES[state]
        total = price + (shipping or Money.zero(price.currency))
        lines = [
            f"{escape(describe_benefit(coupon))} [dim]({KIND_LABELS[coupon.kind]})[/dim]",
            f"Loja: {escape(item.store_name)}",
            f"Preço informado: {total}"
            + (f" (produto {price} + frete {shipping})" if shipping is not None else ""),
            f"Desconto estimado: [bold green]{item.evaluation.discount}[/bold green]",
            f"Total estimado: [bold green]{item.evaluation.final_price}[/bold green]",
            f"Situação: [{style}]{STATE_LABELS[state]}[/{style}] — "
            f"{escape(item.evaluation.reason)}",
        ]
        if coupon.valid_until is not None:
            lines.append(f"Válido até: {coupon.valid_until.strftime('%d/%m/%Y %H:%M')} (UTC)")
        if coupon.min_purchase is not None:
            lines.append(f"Mínimo: {coupon.min_purchase}")
        lines.append(f"[dim]Fonte: {escape(coupon.source)} · {escape(coupon.source_url)}[/dim]")

        console.print(
            Panel(
                "\n".join(lines),
                title=f"CUPOM {escape(coupon.code)}",
                title_align="left",
                border_style="cyan",
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )
    console.print(f"[dim]{VALIDATION_NOTE}[/dim]")
