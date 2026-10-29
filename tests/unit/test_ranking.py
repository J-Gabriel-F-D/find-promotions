"""Testes do score de oportunidade e das curadorias."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from dealhunter.domain.models import DiscountAssessment, OfferView, Promotion
from dealhunter.services import promotions, ranking

NOW = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)


def make_view(
    make_offer_record,
    *,
    price_cents: int = 100_000,
    url: str = "https://loja.example/a",
    classification: str = "normal",
    promotion: Promotion | None = None,
) -> OfferView:
    record = make_offer_record(price_cents=price_cents, url=url)
    return OfferView(
        offer=record.offer,
        product=record.product,
        store=record.store,
        seller=record.seller,
        stats=None,
        discount=DiscountAssessment(classification, "teste"),  # type: ignore[arg-type]
        deal_score=0.0,
        promotion=promotion,
    )


def test_score_expoe_breakdown_e_total(make_offer_record) -> None:
    scored = ranking.score_views([make_view(make_offer_record)], now=NOW)
    assert len(scored) == 1
    breakdown = scored[0].score_breakdown
    for dimension in (
        "price",
        "discount",
        "shipping",
        "trust",
        "history",
        "reviews",
        "urgency",
    ):
        assert dimension in breakdown
    assert breakdown["total"] == scored[0].deal_score
    assert scored[0].trust is not None
    assert scored[0].trust.disclaimer


def test_desconto_suspeito_perde_para_desconto_normal(make_offer_record) -> None:
    normal = make_view(
        make_offer_record, url="https://loja.example/normal", classification="normal"
    )
    suspicious = make_view(
        make_offer_record, url="https://loja.example/suspeito", classification="suspicious"
    )
    scored = ranking.score_views([normal, suspicious], now=NOW)
    by_url = {view.offer.url: view for view in scored}
    assert (
        by_url["https://loja.example/normal"].deal_score
        > by_url["https://loja.example/suspeito"].deal_score
    )


def test_promocao_aberta_recebe_bonus_de_urgencia(make_offer_record) -> None:
    with_promo = make_view(
        make_offer_record,
        url="https://loja.example/promo",
        promotion=Promotion(
            offer_id="off_x",
            kind="flash",
            label="Relâmpago",
            source="fixture",
            source_url="https://loja.example/promo",
            ends_at=NOW + timedelta(hours=1),
        ),
    )
    without = make_view(make_offer_record, url="https://loja.example/sem-promo")
    scored = ranking.score_views([with_promo, without], now=NOW)
    by_url = {view.offer.url: view for view in scored}
    assert by_url["https://loja.example/promo"].score_breakdown["urgency"] == 100.0
    assert by_url["https://loja.example/sem-promo"].score_breakdown["urgency"] == 0.0


def test_select_picks_inclui_relampago_e_nao_inventa_safest_sem_evidencia(
    make_offer_record,
) -> None:
    flash = make_view(
        make_offer_record,
        price_cents=120_000,
        url="https://loja.example/flash",
        promotion=Promotion(
            offer_id="off_flash",
            kind="flash",
            label="Relâmpago",
            source="fixture",
            source_url="https://loja.example/flash",
            ends_at=NOW + timedelta(hours=2),
        ),
    )
    cheap = make_view(make_offer_record, price_cents=90_000, url="https://loja.example/cheap")
    scored = ranking.score_views([flash, cheap], now=NOW)
    picks = ranking.select_picks(scored, now=NOW)

    assert picks["cheapest"] == cheap.offer.id
    assert picks["flash"] == flash.offer.id
    assert picks["safest"] is None


def test_sem_promocao_nao_ha_pick_relampago(make_offer_record) -> None:
    scored = ranking.score_views([make_view(make_offer_record)], now=NOW)
    picks = ranking.select_picks(scored, now=NOW)
    assert picks["flash"] is None


def test_select_flash_ignora_promocao_encerrada(make_offer_record) -> None:
    expired = make_view(
        make_offer_record,
        promotion=Promotion(
            offer_id="off_old",
            kind="flash",
            label="Antiga",
            source="fixture",
            source_url="https://loja.example/a",
            ends_at=NOW - timedelta(hours=1),
        ),
    )
    assert promotions.select_flash([expired], NOW) is None
