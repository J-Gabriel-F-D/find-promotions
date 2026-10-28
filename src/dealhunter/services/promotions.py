"""Janela temporal de promoções e curadoria "relâmpago".

A urgência é um **bônus de ranking** transparente: só existe quando a fonte
declarou uma janela e ela está aberta. Uma oferta sem promoção não é punida
por isso além de não receber o bônus.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from dealhunter.domain.models import OfferView, Promotion, PromotionState


def state_at(promotion: Promotion, now: datetime) -> PromotionState:
    return promotion.state_at(now)


def _seconds_left(promotion: Promotion, now: datetime) -> float | None:
    if promotion.ends_at is None:
        return None
    return max(0.0, (promotion.ends_at - now).total_seconds())


def urgency(promotion: Promotion, now: datetime) -> float:
    """0–100; cresce conforme o fim da janela se aproxima."""
    if promotion.state_at(now) != "active":
        return 0.0
    seconds = _seconds_left(promotion, now)
    if seconds is None:
        return 20.0
    hours = seconds / 3600
    if hours <= 2:
        return 100.0
    if hours <= 6:
        return 85.0
    if hours <= 24:
        return 70.0
    if hours <= 72:
        return 45.0
    return 25.0


def remaining_label(promotion: Promotion, now: datetime) -> str:
    """Texto humano do tempo restante; vazio quando não há prazo."""
    if promotion.ends_at is None:
        return ""
    seconds = _seconds_left(promotion, now) or 0.0
    if seconds <= 0:
        return "encerrada"
    hours = int(seconds // 3600)
    if hours >= 48:
        return f"termina em {hours // 24} dias"
    if hours >= 1:
        minutes = int((seconds % 3600) // 60)
        return f"termina em {hours}h{minutes:02d}"
    return f"termina em {int(seconds // 60)} min"


def select_flash(views: Sequence[OfferView], now: datetime) -> OfferView | None:
    """Melhor promoção declarada como ``flash`` e com janela aberta.

    Promoções ``regular``/``clearance`` não viram pick relâmpago: o selo
    "relâmpago" precisa refletir o tipo declarado pela fonte. Sem janela
    declarada também não há pick.
    """
    active_flash = [
        view
        for view in views
        if view.promotion is not None
        and view.promotion.kind == "flash"
        and view.promotion.state_at(now) == "active"
    ]
    if not active_flash:
        return None
    return max(
        active_flash,
        key=lambda view: (
            urgency(view.promotion, now) if view.promotion else 0.0,
            view.deal_score,
            -view.offer.final_price.cents,
        ),
    )
