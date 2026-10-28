"""Avaliação local de cupons.

Regra central: um cupom **declarado** pela fonte não é um cupom validado. O
cálculo abaixo produz apenas uma *estimativa* de desconto; o preço confirmado
(`Offer.final_price`) nunca é alterado por ele. A validação real exigiria
consultar a loja, o que nem toda fonte permite (e nunca fazemos por scraping).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from dealhunter.domain.models import Coupon, CouponEvaluation, CouponState
from dealhunter.domain.value_objects.money import Money

STATE_LABELS: dict[CouponState, str] = {
    "active": "vigente (declarado pela fonte)",
    "scheduled": "agendado",
    "expired": "expirado",
    "unknown": "sem janela de validade",
}

KIND_LABELS = {
    "percent": "percentual",
    "fixed": "valor fixo",
    "free_shipping": "frete grátis",
}


def describe_benefit(coupon: Coupon) -> str:
    """Texto curto do benefício declarado, sem sugerir que foi validado."""
    if coupon.kind == "percent":
        return f"{coupon.value}% de desconto"
    if coupon.kind == "fixed":
        return f"{Money(coupon.value, coupon.currency)} de desconto"
    return "frete grátis"


def _invalid_reason(coupon: Coupon) -> str | None:
    if not coupon.is_structurally_valid:
        if coupon.kind == "percent":
            return "cupom inválido: percentual deve estar entre 1 e 100"
        if coupon.kind == "fixed":
            return "cupom inválido: valor fixo deve ser positivo"
        return "cupom inválido: frete grátis não leva valor"
    return None


def evaluate(
    coupon: Coupon,
    *,
    price: Money,
    shipping: Money | None,
    now: datetime,
) -> CouponEvaluation:
    """Estima o efeito do cupom sobre ``price`` (produto) e ``shipping``.

    O resultado é sempre ``estimate=True``. Nunca lança: dados ruins de uma
    fonte viram ``applicable=False`` com motivo explícito.
    """
    base = price + (shipping or Money.zero(price.currency))
    zero = Money.zero(price.currency)

    invalid = _invalid_reason(coupon)
    if invalid is not None:
        return CouponEvaluation(coupon, False, invalid, zero, base)

    state = coupon.state_at(now)
    if state == "expired":
        when = coupon.valid_until.strftime("%d/%m/%Y %H:%M") if coupon.valid_until else "?"
        return CouponEvaluation(coupon, False, f"cupom expirado em {when}", zero, base)
    if state == "scheduled":
        when = coupon.valid_from.strftime("%d/%m/%Y %H:%M") if coupon.valid_from else "?"
        return CouponEvaluation(
            coupon, False, f"cupom válido somente a partir de {when}", zero, base
        )

    if coupon.min_purchase is not None and price < coupon.min_purchase:
        return CouponEvaluation(
            coupon,
            False,
            f"valor mínimo de {coupon.min_purchase} não atingido",
            zero,
            base,
        )

    if coupon.kind == "free_shipping":
        if shipping is None:
            return CouponEvaluation(
                coupon, False, "frete não informado: benefício não estimável", zero, base
            )
        discount = shipping
        if discount.cents <= 0:
            return CouponEvaluation(coupon, False, "o frete já é grátis", zero, base)
        final = price
    else:
        if coupon.kind == "percent":
            cents = price.cents * coupon.value // 100
        else:  # fixed
            cents = min(coupon.value, price.cents)
        if coupon.max_discount is not None:
            cents = min(cents, coupon.max_discount.cents)
        discount = Money(max(cents, 0), price.currency)
        if discount.cents <= 0:
            return CouponEvaluation(coupon, False, "cupom sem efeito sobre este preço", zero, base)
        final = base - discount

    if final.cents < 0:
        final = zero
    return CouponEvaluation(coupon, True, "aplicável (estimativa não validada)", discount, final)


def evaluate_all(
    coupons: Sequence[Coupon],
    *,
    price: Money,
    shipping: Money | None,
    now: datetime,
) -> tuple[CouponEvaluation, ...]:
    return tuple(evaluate(coupon, price=price, shipping=shipping, now=now) for coupon in coupons)


def best_evaluation(
    evaluations: Sequence[CouponEvaluation],
) -> CouponEvaluation | None:
    """Melhor cupom aplicável por desconto; ``None`` se nenhum se aplica."""
    applicable = [item for item in evaluations if item.applicable]
    if not applicable:
        return None
    return max(applicable, key=lambda item: item.discount.cents)
