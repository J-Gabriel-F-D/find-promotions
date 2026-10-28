"""Testes de janela, urgência e curadoria relâmpago."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from dealhunter.domain.models import DiscountAssessment, OfferView, Promotion
from dealhunter.services import promotions

NOW = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)


def make_promotion(**overrides: object) -> Promotion:
    data: dict[str, object] = {
        "offer_id": "off_1",
        "kind": "flash",
        "label": "Relâmpago",
        "source": "fixture",
        "source_url": "https://demo.local/oferta",
        "collected_at": NOW,
    }
    data.update(overrides)
    return Promotion(**data)  # type: ignore[arg-type]


def make_view(make_offer_record, *, promotion: Promotion, score: float = 50.0) -> OfferView:
    record = make_offer_record(price_cents=100_000)
    return OfferView(
        offer=record.offer,
        product=record.product,
        store=record.store,
        seller=record.seller,
        stats=None,
        discount=DiscountAssessment("normal", "teste"),
        deal_score=score,
        promotion=promotion,
    )


class TestState:
    def test_promoção_aberta(self) -> None:
        promotion = make_promotion(
            starts_at=NOW - timedelta(hours=1), ends_at=NOW + timedelta(hours=1)
        )
        assert promotion.state_at(NOW) == "active"

    def test_promoção_agendada(self) -> None:
        promotion = make_promotion(starts_at=NOW + timedelta(hours=1))
        assert promotion.state_at(NOW) == "scheduled"

    def test_promoção_encerrada(self) -> None:
        promotion = make_promotion(ends_at=NOW - timedelta(minutes=1))
        assert promotion.state_at(NOW) == "expired"

    def test_promoção_sem_janela(self) -> None:
        assert make_promotion().state_at(NOW) == "unknown"


class TestUrgency:
    def test_terminando_em_poucas_horas_tem_urgencia_maxima(self) -> None:
        promotion = make_promotion(ends_at=NOW + timedelta(hours=1))
        assert promotions.urgency(promotion, NOW) == 100.0

    def test_prazo_longo_tem_urgencia_baixa(self) -> None:
        promotion = make_promotion(ends_at=NOW + timedelta(days=10))
        assert promotions.urgency(promotion, NOW) == 25.0

    def test_promocao_sem_janela_nao_tem_urgencia(self) -> None:
        promotion = make_promotion()
        assert promotions.urgency(promotion, NOW) == 0.0

    def test_promocao_aberta_sem_fim_tem_urgencia_baixa(self) -> None:
        promotion = make_promotion(starts_at=NOW - timedelta(hours=1))
        assert promotion.state_at(NOW) == "active"
        assert promotions.urgency(promotion, NOW) == 20.0

    def test_promoção_encerrada_nao_tem_urgencia(self) -> None:
        promotion = make_promotion(ends_at=NOW - timedelta(minutes=1))
        assert promotions.urgency(promotion, NOW) == 0.0

    def test_rotulo_de_tempo_restante(self) -> None:
        promotion = make_promotion(ends_at=NOW + timedelta(hours=2, minutes=30))
        assert promotions.remaining_label(promotion, NOW) == "termina em 2h30"
        assert promotions.remaining_label(make_promotion(), NOW) == ""


class TestSelectFlash:
    def test_prioriza_promoção_flash(self, make_offer_record) -> None:
        regular = make_view(
            make_offer_record,
            promotion=make_promotion(kind="regular", ends_at=NOW + timedelta(minutes=30)),
            score=90.0,
        )
        flash = make_view(
            make_offer_record,
            promotion=make_promotion(kind="flash", ends_at=NOW + timedelta(hours=5)),
            score=40.0,
        )
        selected = promotions.select_flash([regular, flash], NOW)
        assert selected is not None
        assert selected.promotion is not None
        assert selected.promotion.kind == "flash"

    def test_sem_promoção_aberta_retorna_none(self, make_offer_record) -> None:
        expired = make_view(
            make_offer_record,
            promotion=make_promotion(ends_at=NOW - timedelta(minutes=1)),
        )
        assert promotions.select_flash([expired], NOW) is None

    def test_regular_nao_vira_relampago(self, make_offer_record) -> None:
        regular = make_view(
            make_offer_record,
            promotion=make_promotion(kind="regular", ends_at=NOW + timedelta(days=1)),
        )
        assert promotions.select_flash([regular], NOW) is None
