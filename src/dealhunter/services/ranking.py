"""Ranking de ofertas.

O score aqui e de **oportunidade** (preço/frete/reputacao/histórico), não de
confiabilidade -- o score antifraude entra na Fase 3. Chamar de "confiabilidade"
antes de existir a análise de risco seria enganoso.
"""

from __future__ import annotations

from dataclasses import replace

from dealhunter.application.dto import QuerySpec
from dealhunter.domain.models import OfferView

WEIGHTS = {"price": 0.40, "shipping": 0.15, "reputation": 0.25, "history": 0.20}


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


def score_views(views: list[OfferView]) -> list[OfferView]:
    """Atribui ``deal_score`` proporcional dentro do coorte de ofertas."""
    if not views:
        return []

    prices = [view.offer.final_price.cents for view in views]
    cheapest, priciest = min(prices), max(prices)

    scored: list[OfferView] = []
    for view in views:
        score = (
            WEIGHTS["price"] * _price_component(view, cheapest, priciest)
            + WEIGHTS["shipping"] * _shipping_component(view)
            + WEIGHTS["reputation"] * _reputation_component(view)
            + WEIGHTS["history"] * _history_component(view)
        )
        flags = list(view.flags)
        if not view.offer.shipping_known:
            flags.append("frete_nao_informado")
        if view.stats is None or not view.stats.sufficient_history:
            flags.append("historico_insuficiente")
        if view.seller is None and view.store.reputation is None:
            flags.append("reputacao_desconhecida")
        scored.append(replace(view, deal_score=round(score, 1), flags=tuple(flags)))
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


def select_picks(views: list[OfferView]) -> dict[str, str | None]:
    """Curadorias da Fase 1.

    ``safest`` e ``flash`` ficam nulos de propósito: exigem análise antifraude
    (Fase 3) e janela de promocao (Fase 2). Melhor ausente que inventado.
    """
    if not views:
        return {"best": None, "cheapest": None, "safest": None, "flash": None}

    best = max(views, key=lambda view: (view.deal_score, -view.offer.final_price.cents))
    cheapest = min(views, key=lambda view: view.offer.final_price.cents)
    return {
        "best": best.offer.id,
        "cheapest": cheapest.offer.id,
        "safest": None,
        "flash": None,
    }


def apply_filters(
    views: list[OfferView], spec: QuerySpec
) -> tuple[list[OfferView], dict[str, int]]:
    """Reservado para filtros pos-análise (ex.: score mínimo na Fase 3)."""
    return views, {}
