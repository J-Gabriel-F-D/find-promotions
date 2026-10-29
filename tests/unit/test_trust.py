"""Testes da análise probabilística de confiança e dos sinais antifraude."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from dealhunter.domain.models import (
    DiscountAssessment,
    OfferView,
    PriceStats,
    ReviewSummary,
    TrustAssessment,
    TrustSignal,
)
from dealhunter.services import ranking, trust

NOW = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)


def _view(
    make_offer_record,
    *,
    source: str = "mercadolivre",
    price_cents: int = 100_000,
    url: str = "https://produto.mercadolivre.com.br/MLB-1",
    store_domain: str | None = "mercadolivre.com.br",
    seller_name: str | None = "Vendedor Teste",
    seller_rating: float | None = 4.8,
    store_reputation: float | None = None,
    reviews: ReviewSummary | None = None,
    stats: PriceStats | None = None,
    collected_at: datetime | None = NOW,
    classification: str = "normal",
) -> OfferView:
    record = make_offer_record(
        price_cents=price_cents,
        source=source,
        url=url,
        store_domain=store_domain,
        seller_name=seller_name,
        seller_rating=seller_rating,
    )
    offer = replace(record.offer, collected_at=collected_at)
    store = replace(record.store, reputation=store_reputation)
    return OfferView(
        offer=offer,
        product=record.product,
        store=store,
        seller=record.seller,
        stats=stats,
        discount=DiscountAssessment(classification, "evidência de teste"),  # type: ignore[arg-type]
        deal_score=0.0,
        reviews=reviews,
    )


def _reviews(
    view: OfferView,
    *,
    rating: float = 4.8,
    count: int = 300,
    distribution: dict[int, int] | None = None,
) -> ReviewSummary:
    return ReviewSummary(
        product_id=view.product.id,
        store_id=view.store.id,
        rating_avg=rating,
        rating_count=count,
        source=view.offer.source,
        source_url=view.offer.source_url,
        distribution=distribution or {5: int(count * 0.9), 4: int(count * 0.07), 1: 1},
        confidence=0.8,
    )


def _stats(view: OfferView, *, sufficient: bool = True) -> PriceStats:
    money = view.offer.price
    return PriceStats(
        samples=12 if sufficient else 2,
        days_covered=90 if sufficient else 10,
        minimum=money,
        maximum=money,
        average=money,
        median=money,
        p10=money,
        p25=money,
        p75=money,
        p90=money,
        current=money,
        position_pct=50.0,
        sufficient_history=sufficient,
    )


def test_score_e_confianca_sao_campos_separados(make_offer_record) -> None:
    view = _view(make_offer_record, store_reputation=88.0)
    view = replace(
        view,
        reviews=_reviews(view),
        stats=_stats(view),
        offer=replace(view.offer, confidence=0.95, collected_at=NOW),
    )

    assessment = trust.assess(view, now=NOW)

    assert 0.0 <= assessment.score <= 100.0
    assert 0.0 <= assessment.analysis_confidence <= 1.0
    assert assessment.score != assessment.analysis_confidence
    assert assessment.risk_band in {"low", "moderate", "elevated", "insufficient_data"}
    assert assessment.dimensions
    assert assessment.signals
    assert all(signal.source for signal in assessment.signals)
    assert "não é acusação de fraude" in assessment.disclaimer
    assert "garantia de segurança" in assessment.disclaimer


def test_score_alto_pode_ter_pouca_confianca_de_analise(make_offer_record) -> None:
    # Fonte desconhecida, mas vendedor e desconto favoráveis: score alto com
    # cobertura baixa, pois faltam avaliações e histórico.
    view = _view(
        make_offer_record,
        source="fonte-desconhecida",
        url="https://loja.example/a",
        store_domain="loja.example",
        seller_rating=5.0,
        classification="likely_real",
        collected_at=None,
    )
    assessment = trust.assess(view, now=NOW)
    assert assessment.score >= 60.0
    assert assessment.analysis_confidence < 0.30
    assert assessment.risk_band == "insufficient_data"

    # Muitos dados, mas sinais ruins: score baixo com análise mais coberta.
    bad = _view(
        make_offer_record,
        store_reputation=20.0,
        seller_rating=1.0,
        classification="suspicious",
    )
    bad = replace(bad, reviews=_reviews(bad, rating=1.0, count=100), stats=_stats(bad))
    bad_assessment = trust.assess(bad, now=NOW)
    assert bad_assessment.score < 60.0
    assert bad_assessment.analysis_confidence > assessment.analysis_confidence


def test_fonte_de_demonstracao_reduz_confianca_com_os_mesmos_dados(
    make_offer_record,
) -> None:
    demo = _view(
        make_offer_record,
        source="fixture",
        url="https://loja.example/a",
        store_domain="loja.example",
    )
    official = _view(
        make_offer_record,
        source="mercadolivre",
        url="https://loja.example/a",
        store_domain="loja.example",
    )

    assert trust.assess(official, now=NOW).score > trust.assess(demo, now=NOW).score


def test_desconto_suspeito_reduz_confianca_sem_acusar_fraude(make_offer_record) -> None:
    normal = _view(make_offer_record, classification="normal")
    suspicious = _view(make_offer_record, classification="suspicious")

    normal_trust = trust.assess(normal, now=NOW)
    suspicious_trust = trust.assess(suspicious, now=NOW)

    assert suspicious_trust.score < normal_trust.score
    assert any(
        signal.dimension == "price" and signal.direction == "negative"
        for signal in suspicious_trust.signals
    )
    assert "fraudulento" not in suspicious_trust.disclaimer.lower()


def test_avaliacao_com_amostra_pequena_encolhe_para_o_neutro(make_offer_record) -> None:
    base = _view(make_offer_record)
    small = replace(base, reviews=_reviews(base, rating=5.0, count=1))
    large = replace(base, reviews=_reviews(base, rating=4.8, count=500))

    assert trust.assess(large, now=NOW).score > trust.assess(small, now=NOW).score
    small_assessment = trust.assess(small, now=NOW)
    assert any("pequena" in limitation for limitation in small_assessment.limitations)


def test_dominio_divergente_e_sinal_negativo(make_offer_record) -> None:
    matching = _view(
        make_offer_record,
        source="feed",
        url="https://loja.example/a",
        store_domain="loja.example",
    )
    mismatching = _view(
        make_offer_record,
        source="feed",
        url="https://outro.example/a",
        store_domain="loja.example",
    )

    matching_trust = trust.assess(matching, now=NOW)
    mismatching_trust = trust.assess(mismatching, now=NOW)

    assert mismatching_trust.score < matching_trust.score
    assert any("difere" in signal.evidence for signal in mismatching_trust.signals)


def test_dados_antigos_reduzem_score_e_confianca(make_offer_record) -> None:
    fresh = _view(make_offer_record, collected_at=NOW)
    stale = _view(make_offer_record, collected_at=NOW - timedelta(days=200))

    fresh_trust = trust.assess(fresh, now=NOW)
    stale_trust = trust.assess(stale, now=NOW)

    assert stale_trust.score < fresh_trust.score
    assert stale_trust.analysis_confidence <= fresh_trust.analysis_confidence
    assert any("90 dias" in limitation for limitation in stale_trust.limitations)


def test_sem_evidencia_nao_gera_pick_safest(make_offer_record) -> None:
    view = _view(
        make_offer_record,
        source="fonte-desconhecida",
        url="https://loja.example/a",
        store_domain=None,
        seller_name=None,
        seller_rating=None,
        collected_at=None,
    )
    scored = ranking.score_views([view], now=NOW)
    picks = ranking.select_picks(scored, now=NOW)

    assert scored[0].trust is not None
    assert scored[0].trust.risk_band == "insufficient_data"
    assert picks["safest"] is None


def test_safest_prioriza_confianca_e_nao_preco(make_offer_record) -> None:
    cheap = _view(
        make_offer_record,
        price_cents=70_000,
        seller_rating=2.0,
        classification="suspicious",
    )
    cheap = replace(cheap, reviews=_reviews(cheap, rating=2.0, count=40), stats=_stats(cheap))
    trusted = _view(
        make_offer_record,
        price_cents=120_000,
        seller_rating=4.9,
        store_reputation=90.0,
        classification="normal",
    )
    trusted = replace(
        trusted, reviews=_reviews(trusted, rating=4.9, count=500), stats=_stats(trusted)
    )

    scored = ranking.score_views([cheap, trusted], now=NOW)
    picks = ranking.select_picks(scored, now=NOW)

    assert picks["cheapest"] == cheap.offer.id
    assert picks["safest"] == trusted.offer.id


def test_assessment_e_sinal_rejeitam_valores_invalidos() -> None:
    with pytest.raises(ValueError):
        TrustAssessment(score=101.0, analysis_confidence=0.5, risk_band="low")
    with pytest.raises(ValueError):
        TrustAssessment(score=50.0, analysis_confidence=1.5, risk_band="low")
    with pytest.raises(ValueError):
        TrustSignal(
            code="x",
            dimension="store",
            direction="neutral",
            weight=1.5,
            confidence=0.5,
            evidence="x",
            source="x",
        )


def test_score_de_confianca_tem_evidencia_rastreavel(make_offer_record) -> None:
    view = _view(make_offer_record)
    view = replace(
        view,
        reviews=_reviews(view),
        stats=_stats(view),
        offer=replace(view.offer, collected_at=NOW),
    )
    assessment = trust.assess(view, now=NOW)

    for signal in assessment.signals:
        assert signal.code
        assert signal.dimension
        assert 0.0 <= signal.weight <= 1.0
        assert 0.0 <= signal.confidence <= 1.0
        assert signal.evidence
        assert signal.source
    assert assessment.rules_version == "trust-v1"
    assert assessment.disclaimer
