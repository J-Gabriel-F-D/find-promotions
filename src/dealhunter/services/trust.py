"""Análise probabilística de confiança, separada do score de oportunidade.

Princípios:

* só usa dados observáveis (fonte, loja, vendedor, avaliações agregadas,
  histórico próprio, desconto corroborado e frescor);
* ``analysis_confidence`` mede cobertura de evidência, não probabilidade de
  fraude;
* ausência de dado gera limitação, nunca acusação;
* a saída usa "sinais" e "faixas de risco", jamais "loja segura" ou
  "loja fraudulenta".
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from math import log1p
from urllib.parse import urlsplit

from dealhunter.domain.models import (
    TRUST_DISCLAIMER,
    OfferView,
    TrustAssessment,
    TrustBand,
    TrustDirection,
    TrustSignal,
)

TRUST_RULES_VERSION = "trust-v1"

# Pesos das dimensões. "payment" não é coletado hoje; fica explícito no
# denominador para que a confiança da análise não seja inflada.
DIMENSION_WEIGHTS: dict[str, float] = {
    "price": 0.25,
    "history": 0.15,
    "store": 0.15,
    "seller": 0.15,
    "reputation": 0.10,
    "payment": 0.10,
    "freshness": 0.10,
}

# Prior por procedência do dado. Não é uma opinião sobre o vendedor: é um
# ponto de partida sobre a qualidade da fonte, sempre exibido como evidência.
SOURCE_PRIORS: dict[str, tuple[float, float, str]] = {
    "mercadolivre": (72.0, 0.60, "API oficial do Mercado Livre"),
    "feed": (55.0, 0.40, "feed JSON configurado"),
    "fixture": (12.0, 0.30, "dados fictícios de demonstração"),
}
_UNKNOWN_SOURCE = (40.0, 0.20, "fonte sem histórico de confiabilidade")

_PRICE_SCORES = {
    "likely_real": (82.0, 0.75),
    "normal": (58.0, 0.45),
    "suspicious": (25.0, 0.65),
    "insufficient_evidence": (50.0, 0.15),
}

SAFEST_MIN_SCORE = 50.0
SAFEST_MIN_CONFIDENCE = 0.30
_INSUFFICIENT_CONFIDENCE = 0.30
_LOW_RISK_SCORE = 70.0
_LOW_RISK_CONFIDENCE = 0.45
_ELEVATED_RISK_SCORE = 40.0


@dataclass(frozen=True, slots=True)
class _Dimension:
    code: str
    dimension: str
    score: float
    confidence: float
    evidence: str
    source: str
    limitation: str | None = None


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(value, high))


def _direction(score: float) -> TrustDirection:
    if score >= 65.0:
        return "positive"
    if score < 45.0:
        return "negative"
    return "neutral"


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _domain_match(url: str, domain: str | None) -> bool | None:
    """Compara o host do anúncio com o domínio declarado, sem resolver DNS."""
    if not domain:
        return None
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return None
    if not host:
        return None
    host = host.lower().rstrip(".")
    declared = domain.lower().strip().rstrip(".")
    if not declared:
        return None
    return host == declared or host.endswith(f".{declared}") or declared.endswith(f".{host}")


def _store_dimension(view: OfferView) -> _Dimension:
    source_id = view.offer.source or "unknown"
    prior_score, prior_conf, source_label = SOURCE_PRIORS.get(source_id, _UNKNOWN_SOURCE)
    declared_confidence = _clamp(view.offer.confidence, 0.0, 1.0)
    score = 0.70 * prior_score + 0.30 * declared_confidence * 100
    confidence = prior_conf
    evidence = f"fonte: {source_label}; confiança declarada {declared_confidence:.2f}"

    if view.store.reputation is not None:
        reputation = _clamp(view.store.reputation)
        score = score * 0.65 + reputation * 0.35
        confidence = min(1.0, confidence + 0.25)
        evidence += f"; reputação da loja {reputation:.0f}/100"

    match = _domain_match(view.offer.url, view.store.domain)
    if match is True:
        score = min(100.0, score + 5.0)
        confidence = min(1.0, confidence + 0.10)
        evidence += "; domínio do anúncio coincide com o da loja"
    elif match is False:
        score = max(0.0, score - 20.0)
        confidence = min(1.0, confidence + 0.15)
        evidence += "; domínio do anúncio difere do domínio declarado pela loja"

    if not view.offer.url.lower().startswith("https://"):
        score = max(0.0, score - 10.0)
        evidence += "; URL do anúncio não usa HTTPS"

    return _Dimension(
        code="procedencia_loja",
        dimension="store",
        score=_clamp(score),
        confidence=confidence,
        evidence=evidence,
        source=source_id,
    )


def _seller_dimension(view: OfferView) -> _Dimension | None:
    seller = view.seller
    if seller is None:
        return None

    if seller.rating is not None:
        rating = _clamp(seller.rating, 0.0, 5.0)
        sales = seller.sales_count if seller.sales_count and seller.sales_count > 0 else 20
        sample = max(1, min(sales, 1_000))
        prior_weight = 10
        score = (rating / 5 * 100 * sample + 50 * prior_weight) / (sample + prior_weight)
        confidence = 0.25 + 0.35 * min(1.0, log1p(sample) / log1p(1_000))
        evidence = f"vendedor {rating:.1f}/5"
        if seller.sales_count:
            evidence += f"; {seller.sales_count} vendas informadas"
        else:
            evidence += "; volume de vendas não informado"
        return _Dimension(
            code="reputacao_vendedor",
            dimension="seller",
            score=_clamp(score),
            confidence=confidence,
            evidence=evidence,
            source=seller.source,
        )

    if seller.sales_count:
        return _Dimension(
            code="volume_vendedor",
            dimension="seller",
            score=55.0,
            confidence=0.20,
            evidence=f"vendedor com {seller.sales_count} vendas, sem nota informada",
            source=seller.source,
            limitation="nota do vendedor não informada",
        )
    return None


def _reviews_dimension(view: OfferView) -> _Dimension | None:
    reviews = view.reviews
    if reviews is None or reviews.rating_count <= 0:
        return None

    rating = _clamp(reviews.rating_avg, 0.0, 5.0)
    count = min(reviews.rating_count, 10_000)
    prior_weight = 20
    score = (rating / 5 * 100 * count + 50 * prior_weight) / (count + prior_weight)
    evidence = f"avaliações agregadas {rating:.1f}/5 em {reviews.rating_count}"
    limitation: str | None = None

    if reviews.distribution:
        negative = reviews.negative_share
        score -= negative * 30
        evidence += f"; 1-2 estrelas {negative * 100:.1f}%"
        confidence = 0.20 + 0.55 * min(1.0, count / 200) + 0.10
    else:
        confidence = 0.20 + 0.55 * min(1.0, count / 200)
        limitation = "distribuição de estrelas não informada"

    if reviews.rating_count < 10:
        limitation = "amostra pequena de avaliações"
    confidence = min(0.90, confidence) * (0.75 + 0.25 * _clamp(reviews.confidence, 0.0, 1.0))

    return _Dimension(
        code="avaliacoes_agregadas",
        dimension="reputation",
        score=_clamp(score),
        confidence=confidence,
        evidence=evidence,
        source=reviews.source,
        limitation=limitation,
    )


def _price_dimension(view: OfferView) -> _Dimension:
    classification = view.discount.classification
    score, confidence = _PRICE_SCORES.get(classification, (50.0, 0.15))
    if view.stats is not None and view.stats.sufficient_history:
        confidence = min(1.0, confidence + 0.10)
    evidence = f"desconto {classification}: {view.discount.evidence}"
    limitation = None
    if classification == "insufficient_evidence":
        limitation = "histórico insuficiente para corroborar o desconto"
    return _Dimension(
        code="desconto_corroborado",
        dimension="price",
        score=score,
        confidence=confidence,
        evidence=evidence,
        source="pricing",
        limitation=limitation,
    )


def _history_dimension(view: OfferView) -> _Dimension | None:
    stats = view.stats
    if stats is None:
        return None
    evidence = f"histórico próprio com {stats.samples} amostra(s) em {stats.days_covered} dia(s)"
    if stats.sufficient_history:
        return _Dimension(
            code="historico_proprio",
            dimension="history",
            score=80.0,
            confidence=0.80,
            evidence=evidence,
            source="pricing",
        )
    return _Dimension(
        code="historico_limitado",
        dimension="history",
        score=50.0,
        confidence=min(0.30, 0.05 + stats.samples / 8 * 0.25),
        evidence=evidence,
        source="pricing",
        limitation="histórico de preços ainda insuficiente",
    )


def _freshness_dimension(view: OfferView, now: datetime) -> _Dimension | None:
    collected_at = view.offer.collected_at
    if collected_at is None:
        return None
    age_days = max(0.0, (_aware(now) - _aware(collected_at)).total_seconds() / 86_400)
    if age_days <= 7:
        score, confidence = 85.0, 0.60
    elif age_days <= 30:
        score, confidence = 70.0, 0.50
    elif age_days <= 90:
        score, confidence = 50.0, 0.35
    else:
        score, confidence = 25.0, 0.20
    limitation = None
    if age_days > 90:
        limitation = "dados coletados há mais de 90 dias"
    return _Dimension(
        code="frescor_coleta",
        dimension="freshness",
        score=score,
        confidence=confidence,
        evidence=f"coletado há {age_days:.0f} dia(s)",
        source=view.offer.source,
        limitation=limitation,
    )


def _risk_band(score: float, confidence: float) -> TrustBand:
    if confidence < _INSUFFICIENT_CONFIDENCE:
        return "insufficient_data"
    if score >= _LOW_RISK_SCORE and confidence >= _LOW_RISK_CONFIDENCE:
        return "low"
    if score < _ELEVATED_RISK_SCORE:
        return "elevated"
    return "moderate"


def assess(view: OfferView, *, now: datetime) -> TrustAssessment:
    """Avalia uma oferta sem afirmar fraude ou segurança absoluta."""
    dimensions: list[tuple[str, _Dimension]] = []
    for name, dimension in (
        ("store", _store_dimension(view)),
        ("seller", _seller_dimension(view)),
        ("reputation", _reviews_dimension(view)),
        ("price", _price_dimension(view)),
        ("history", _history_dimension(view)),
        ("freshness", _freshness_dimension(view, now)),
    ):
        if dimension is not None:
            dimensions.append((name, dimension))

    limitations: list[str] = ["meio de pagamento não analisado (dado não coletado)"]
    if view.seller is None:
        limitations.append("reputação do vendedor não informada")
    if view.reviews is None:
        limitations.append("avaliações agregadas não disponíveis")
    if view.stats is None:
        limitations.append("sem histórico de preços coletado")
    if view.offer.collected_at is None:
        limitations.append("data de coleta ausente")

    total_weight = 0.0
    weighted_score = 0.0
    dimension_scores: dict[str, float] = {}
    signals: list[TrustSignal] = []

    for name, dimension in dimensions:
        effective_weight = DIMENSION_WEIGHTS[name] * dimension.confidence
        if effective_weight <= 0:
            continue
        total_weight += effective_weight
        weighted_score += dimension.score * effective_weight
        dimension_scores[name] = round(dimension.score, 1)
        signals.append(
            TrustSignal(
                code=dimension.code,
                dimension=name,
                direction=_direction(dimension.score),
                weight=round(effective_weight, 3),
                confidence=round(dimension.confidence, 3),
                evidence=dimension.evidence,
                source=dimension.source,
            )
        )
        if dimension.limitation:
            limitations.append(dimension.limitation)

    score = weighted_score / total_weight if total_weight else 50.0
    coverage = total_weight / sum(DIMENSION_WEIGHTS.values())
    confidence = _clamp(coverage, 0.0, 1.0)
    rounded_score = round(score, 1)
    rounded_confidence = round(confidence, 2)

    return TrustAssessment(
        score=rounded_score,
        analysis_confidence=rounded_confidence,
        risk_band=_risk_band(rounded_score, rounded_confidence),
        dimensions=dimension_scores,
        signals=tuple(signals),
        limitations=tuple(dict.fromkeys(limitations)),
        rules_version=TRUST_RULES_VERSION,
        disclaimer=TRUST_DISCLAIMER,
    )


def enrich(views: list[OfferView], *, now: datetime) -> list[OfferView]:
    """Preenche ``trust`` sem alterar ofertas que já trazem uma análise."""
    return [
        view if view.trust is not None else replace(view, trust=assess(view, now=now))
        for view in views
    ]
