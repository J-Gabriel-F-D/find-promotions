"""Ranking de ofertas.

O score aqui e de **oportunidade** (preço/desconto/frete/reputacao/histórico/
avaliações/urgência), não de confiabilidade -- o score antifraude entra na
Fase 3. Chamar de "confiabilidade" antes de existir a análise de risco seria
enganoso.

Cada dimensão é exposta em ``score_breakdown`` para que a recomendação possa ser
explicada, e não apenas exibida como um número mágico.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from dealhunter.application.dto import QuerySpec
from dealhunter.domain.models import OfferView
from dealhunter.services import promotions

WEIGHTS = {
    "price": 0.25,
    "discount": 0.20,
    "shipping": 0.10,
    "reputation": 0.20,
    "history": 0.15,
    "reviews": 0.05,
    "urgency": 0.05,
}

_DISCOUNT_SCORES = {
    "likely_real": 100.0,
    "normal": 60.0,
    "suspicious": 0.0,
    "insufficient_evidence": 50.0,
}


def _price_component(view: OfferView, cheapest: int, priciest: int) -> float:
    if priciest <= cheapest:
        return 60.0
    span = priciest - cheapest
    return (1 - (view.offer.final_price.cents - cheapest) / span) * 100


def _shipping_component(view: OfferView) -> float:
    if not view.offer.shipping_known:
        return 40.0
    return 100.0 if view.offer.final_price == view.offer.price else 50.0


def _reputation_component(view: OfferView) -> float:
    if view.seller is not None and view.seller.rating is not None:
        return max(0.0, min(view.seller.rating / 5 * 100, 100.0))
    if view.store.reputation is not None:
        return max(0.0, min(view.store.reputation, 100.0))
    return 50.0


def _history_component(view: OfferView) -> float:
    if view.stats is None or not view.stats.sufficient_history:
        return 50.0
    return max(0.0, min(100.0 - view.stats.position_pct, 100.0))


def _discount_component(view: OfferView) -> float:
    """Desconto anunciado vale só o que a nossa série histórica sustenta."""
    return _DISCOUNT_SCORES[view.discount.classification]


def _reviews_component(view: OfferView) -> float:
    """Nota da fonte, encolhida para 50 quando há poucas avaliações."""
    reviews = view.reviews
    if reviews is None or reviews.rating_count <= 0:
        return 50.0
    rating_score = max(0.0, min(reviews.rating_avg / 5 * 100, 100.0))
    confidence = min(reviews.rating_count / 20, 1.0)
    return 50.0 + (rating_score - 50.0) * confidence


def _urgency_component(view: OfferView, now: datetime) -> float:
    if view.promotion is None:
        return 0.0
    return promotions.urgency(view.promotion, now)


def score_views(views: list[OfferView], *, now: datetime | None = None) -> list[OfferView]:
    """Atribui ``deal_score`` proporcional dentro do coorte de ofertas."""
    if not views:
        return []

    prices = [view.offer.final_price.cents for view in views]
    cheapest, priciest = min(prices), max(prices)

    scored: list[OfferView] = []
    for view in views:
        components = {
            "price": round(_price_component(view, cheapest, priciest), 1),
            "discount": round(_discount_component(view), 1),
            "shipping": round(_shipping_component(view), 1),
            "reputation": round(_reputation_component(view), 1),
            "history": round(_history_component(view), 1),
            "reviews": round(_reviews_component(view), 1),
            "urgency": round(_urgency_component(view, now) if now else 0.0, 1),
        }
        score = sum(WEIGHTS[name] * value for name, value in components.items())
        components["total"] = round(score, 1)

        flags = list(view.flags)
        if not view.offer.shipping_known:
            flags.append("frete_nao_informado")
        if view.stats is None or not view.stats.sufficient_history:
            flags.append("historico_insuficiente")
        if view.seller is None and view.store.reputation is None:
            flags.append("reputacao_desconhecida")
        if view.best_coupon is not None:
            flags.append("cupom_nao_validado")
        if view.promotion is not None and now and view.promotion.state_at(now) == "unknown":
            flags.append("promocao_sem_janela")
        scored.append(
            replace(
                view,
                deal_score=round(score, 1),
                flags=tuple(dict.fromkeys(flags)),
                score_breakdown=components,
            )
        )
    return scored


def sort_views(views: list[OfferView], mode: str) -> list[OfferView]:
    if mode == "price":
        return sorted(views, key=lambda view: view.offer.final_price.cents)
    if mode == "reputation":
        return sorted(
            views,
            key=lambda view: (
                -(view.seller.rating if view.seller and view.seller.rating else 0.0),
                view.offer.final_price.cents,
            ),
        )
    return sorted(views, key=lambda view: (-view.deal_score, view.offer.final_price.cents))


def select_picks(views: list[OfferView], *, now: datetime) -> dict[str, str | None]:
    """Curadorias da Fase 2.

    ``safest`` continua nulo de propósito: exige análise antifraude (Fase 3).
    ``flash`` só aponta para promoção declarada como ``flash`` e com janela
    aberta pela fonte.
    """
    if not views:
        return {"best": None, "cheapest": None, "safest": None, "flash": None}

    best = max(views, key=lambda view: (view.deal_score, -view.offer.final_price.cents))
    cheapest = min(views, key=lambda view: view.offer.final_price.cents)
    flash = promotions.select_flash(views, now)
    return {
        "best": best.offer.id,
        "cheapest": cheapest.offer.id,
        "safest": None,
        "flash": flash.offer.id if flash else None,
    }


def apply_filters(
    views: list[OfferView], spec: QuerySpec
) -> tuple[list[OfferView], dict[str, int]]:
    """Reservado para filtros pos-análise (ex.: score mínimo na Fase 3)."""
    return views, {}
