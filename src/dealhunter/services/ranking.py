"""Ranking de ofertas.

O ``deal_score`` continua sendo de **oportunidade**, mas agora inclui também o
componente de confiança calculado separadamente. Confiança e oportunidade não
são a mesma coisa: ``view.trust.score`` e ``view.trust.analysis_confidence``
ficam em um objeto próprio e nunca são escondidos dentro de um único número.

Cada dimensão é exposta em ``score_breakdown`` e em ``trust.signals`` para que
a recomendação possa ser explicada.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from dealhunter.application.dto import QuerySpec
from dealhunter.domain.models import OfferView, TrustAssessment
from dealhunter.services import promotions, trust

WEIGHTS = {
    "price": 0.30,
    "discount": 0.15,
    "history": 0.15,
    "trust": 0.15,
    "reviews": 0.10,
    "shipping": 0.05,
    "urgency": 0.10,
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

    effective_now = now or datetime.now(UTC)
    views = trust.enrich(views, now=effective_now)
    prices = [view.offer.final_price.cents for view in views]
    cheapest, priciest = min(prices), max(prices)

    scored: list[OfferView] = []
    for view in views:
        assessment = view.trust or trust.assess(view, now=effective_now)
        components = {
            "price": round(_price_component(view, cheapest, priciest), 1),
            "discount": round(_discount_component(view), 1),
            "shipping": round(_shipping_component(view), 1),
            "trust": round(assessment.score, 1),
            "history": round(_history_component(view), 1),
            "reviews": round(_reviews_component(view), 1),
            "urgency": round(
                _urgency_component(view, effective_now) if now is not None else 0.0, 1
            ),
        }
        score = sum(WEIGHTS[name] * value for name, value in components.items())
        # Penalidade apenas por sinais observáveis (desconto não corroborado e
        # faixa de risco elevada). Não é uma acusação de fraude.
        risk_penalty = 0.0
        if view.discount.classification == "suspicious":
            risk_penalty += 5.0
        if assessment.analysis_confidence < trust.SAFEST_MIN_CONFIDENCE:
            risk_penalty += 2.0
        if assessment.risk_band == "elevated":
            risk_penalty += min(10.0, max(0.0, 50.0 - assessment.score) * 0.4)
        score = max(0.0, score - risk_penalty)
        if risk_penalty:
            components["risk_penalty"] = round(risk_penalty, 1)
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
        if assessment.analysis_confidence < trust.SAFEST_MIN_CONFIDENCE:
            flags.append("analise_confianca_limitada")
        if assessment.risk_band == "elevated":
            flags.append("sinais_de_atencao")
        scored.append(
            replace(
                view,
                deal_score=round(score, 1),
                flags=tuple(dict.fromkeys(flags)),
                score_breakdown=components,
                trust=assessment,
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
    """Curadorias: melhor geral, menor preço, mais confiável e relâmpago.

    ``safest`` só é preenchido quando a análise de confiança tem evidência
    mínima (``analysis_confidence``) e score suficiente. Caso contrário fica
    nulo: não inventamos uma recomendação de confiança.
    """
    if not views:
        return {"best": None, "cheapest": None, "safest": None, "flash": None}

    best = max(views, key=lambda view: (view.deal_score, -view.offer.final_price.cents))
    cheapest = min(views, key=lambda view: view.offer.final_price.cents)
    flash = promotions.select_flash(views, now)
    safest_candidates: list[tuple[OfferView, TrustAssessment]] = []
    for view in views:
        assessment = view.trust or trust.assess(view, now=now)
        if (
            assessment.score >= trust.SAFEST_MIN_SCORE
            and assessment.analysis_confidence >= trust.SAFEST_MIN_CONFIDENCE
        ):
            safest_candidates.append((view, assessment))
    safest = (
        max(
            safest_candidates,
            key=lambda item: (
                item[1].score,
                item[1].analysis_confidence,
                -item[0].offer.final_price.cents,
            ),
        )[0]
        if safest_candidates
        else None
    )
    return {
        "best": best.offer.id,
        "cheapest": cheapest.offer.id,
        "safest": safest.offer.id if safest else None,
        "flash": flash.offer.id if flash else None,
    }


def apply_filters(
    views: list[OfferView], spec: QuerySpec
) -> tuple[list[OfferView], dict[str, int]]:
    """Reservado para filtros pós-análise (ex.: score mínimo de confiança)."""
    return views, {}
