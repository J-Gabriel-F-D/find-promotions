"""Modelos de dominio da Fase 1 (MVP).

Nenhum destes objetos conhece banco de dados, HTTP ou terminal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from dealhunter.domain.ids import stable_id
from dealhunter.domain.value_objects.money import Money

Condition = Literal["new", "used", "refurbished"]
DiscountClass = Literal["likely_real", "normal", "suspicious", "insufficient_evidence"]
CouponKind = Literal["percent", "fixed", "free_shipping"]
CouponState = Literal["active", "scheduled", "expired", "unknown"]
PromotionKind = Literal["flash", "regular", "clearance"]
PromotionState = Literal["active", "scheduled", "expired", "unknown"]


@dataclass(frozen=True, slots=True)
class Store:
    name: str
    domain: str | None = None
    reputation: float | None = None
    source: str = "unknown"

    @property
    def id(self) -> str:
        return stable_id("str", self.domain or self.name)


@dataclass(frozen=True, slots=True)
class Seller:
    name: str
    store_id: str | None = None
    rating: float | None = None
    sales_count: int | None = None
    source: str = "unknown"

    @property
    def id(self) -> str:
        return stable_id("sel", self.store_id or "", self.name)


@dataclass(frozen=True, slots=True)
class Product:
    """Produto canonico (apos deduplicacao)."""

    title: str
    brand: str | None = None
    model: str | None = None
    family: str | None = None
    storage_gb: int | None = None
    ram_gb: int | None = None
    gtin: str | None = None
    mpn: str | None = None
    condition: Condition = "new"
    identity_kind: str = "title"
    identity_value: str = ""
    specs: dict[str, str] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return stable_id("prd", self.identity_kind, self.identity_value)


@dataclass(frozen=True, slots=True)
class Offer:
    """Oferta de uma loja para um produto."""

    product_id: str
    store_id: str
    seller_id: str | None
    url: str
    source: str
    source_url: str
    price: Money
    list_price: Money | None = None
    shipping: Money | None = None
    installments: int | None = None
    installment_value: Money | None = None
    condition: Condition = "new"
    availability: str = "unknown"
    coupon_code: str | None = None
    collected_at: datetime | None = None
    confidence: float = 1.0

    @property
    def id(self) -> str:
        return stable_id("off", self.source, self.url)

    @property
    def final_price(self) -> Money:
        """Preço do produto + frete conhecido."""
        return self.price + (self.shipping or Money.zero(self.price.currency))

    @property
    def shipping_known(self) -> bool:
        return self.shipping is not None


@dataclass(frozen=True, slots=True)
class CollectedCoupon:
    """Cupom cru anunciado pela fonte. A fonte apenas **declara**; não validamos."""

    code: str
    kind: CouponKind
    value: int
    min_purchase_cents: int | None = None
    max_discount_cents: int | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    currency: str = "BRL"
    confidence: float = 0.6


@dataclass(frozen=True, slots=True)
class CollectedPromotion:
    """Janela promocional declarada pela fonte."""

    kind: PromotionKind
    label: str = ""
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    confidence: float = 0.6


@dataclass(frozen=True, slots=True)
class CollectedReviews:
    """Agregado de avaliações publicado pela fonte (nunca texto inventado)."""

    rating: float
    count: int
    distribution: dict[int, int] = field(default_factory=dict)
    confidence: float = 0.6


@dataclass(frozen=True, slots=True)
class CollectedOffer:
    """Oferta crua devolvida por um adapter, antes de normalização/persistencia."""

    source_id: str
    title: str
    url: str
    source_url: str
    price_cents: int
    currency: str = "BRL"
    list_price_cents: int | None = None
    shipping_cents: int | None = None
    store_name: str = ""
    store_domain: str | None = None
    seller_name: str | None = None
    seller_rating: float | None = None
    seller_sales: int | None = None
    condition: Condition = "new"
    availability: str = "unknown"
    installments: int | None = None
    installment_cents: int | None = None
    coupon_code: str | None = None
    gtin: str | None = None
    mpn: str | None = None
    brand: str | None = None
    specs: dict[str, str] = field(default_factory=dict)
    collected_at: datetime | None = None
    confidence: float = 0.8
    # Série historica opcional (apenas fontes de demonstração/backfill).
    history: tuple[tuple[int, int], ...] = ()
    """Tuplas ``(dias_atras, preco_em_centavos)``."""
    coupons: tuple[CollectedCoupon, ...] = ()
    promotion: CollectedPromotion | None = None
    reviews: CollectedReviews | None = None

    @property
    def price(self) -> Money:
        return Money(self.price_cents, self.currency)


@dataclass(frozen=True, slots=True)
class Coupon:
    """Cupom declarado por uma loja/fonte.

    ``last_verified_at`` só é preenchido quando **nós** confirmamos a vigência
    junto à loja. Enquanto isso, o cupom é sempre apresentado como não validado.
    """

    store_id: str
    code: str
    kind: CouponKind
    value: int
    source: str
    source_url: str
    min_purchase: Money | None = None
    max_discount: Money | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    collected_at: datetime | None = None
    last_verified_at: datetime | None = None
    confidence: float = 0.5

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", self.code.strip().upper())

    @property
    def id(self) -> str:
        # Identidade = (loja, código). Uma nova janela de validade atualiza o
        # mesmo cupom em vez de duplicá-lo a cada coleta.
        return stable_id("cpn", self.store_id, self.code)

    @property
    def currency(self) -> str:
        for money in (self.min_purchase, self.max_discount):
            if money is not None:
                return money.currency
        return "BRL"

    @property
    def is_structurally_valid(self) -> bool:
        if not self.code:
            return False
        if self.kind == "percent":
            return 1 <= self.value <= 100
        if self.kind == "fixed":
            return self.value > 0
        return self.value == 0

    @property
    def validation(self) -> Literal["store_verified", "unverified"]:
        return "store_verified" if self.last_verified_at else "unverified"

    def state_at(self, now: datetime) -> CouponState:
        if self.valid_until is not None and now >= self.valid_until:
            return "expired"
        if self.valid_from is not None and now < self.valid_from:
            return "scheduled"
        if self.valid_from is None and self.valid_until is None:
            return "unknown"
        return "active"


@dataclass(frozen=True, slots=True)
class CouponEvaluation:
    """Efeito estimado de um cupom sobre uma oferta.

    ``estimate=True`` é invariante: cupom não validado nunca entra no preço
    confirmado, apenas em ``final_price`` estimado.
    """

    coupon: Coupon
    applicable: bool
    reason: str
    discount: Money
    final_price: Money
    estimate: bool = True


@dataclass(frozen=True, slots=True)
class Promotion:
    """Promoção com janela temporal associada a uma oferta."""

    offer_id: str
    kind: PromotionKind
    label: str
    source: str
    source_url: str
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    collected_at: datetime | None = None
    confidence: float = 0.5

    @property
    def id(self) -> str:
        # Estado atual da promoção por oferta/tipo; o histórico de preços vive
        # em offer_snapshot, não aqui.
        return stable_id("prm", self.offer_id, self.kind)

    def state_at(self, now: datetime) -> PromotionState:
        if self.starts_at is not None and now < self.starts_at:
            return "scheduled"
        if self.ends_at is not None and now >= self.ends_at:
            return "expired"
        if self.starts_at is None and self.ends_at is None:
            return "unknown"
        return "active"


@dataclass(frozen=True, slots=True)
class ReviewSummary:
    """Agregado de avaliações publicado por uma loja (sem texto individual)."""

    product_id: str
    store_id: str
    rating_avg: float
    rating_count: int
    source: str
    source_url: str
    distribution: dict[int, int] = field(default_factory=dict)
    collected_at: datetime | None = None
    last_verified_at: datetime | None = None
    confidence: float = 0.5

    @property
    def id(self) -> str:
        return stable_id("rev", self.product_id, self.store_id, self.source)

    @property
    def negative_share(self) -> float:
        if self.rating_count <= 0:
            return 0.0
        negative = sum(self.distribution.get(score, 0) for score in (1, 2))
        return round(negative / self.rating_count, 3)


@dataclass(frozen=True, slots=True)
class PriceStats:
    samples: int
    days_covered: int
    minimum: Money
    maximum: Money
    average: Money
    median: Money
    p10: Money
    p25: Money
    p75: Money
    p90: Money
    current: Money
    position_pct: float
    sufficient_history: bool

    def discount_vs_average(self) -> float:
        if self.average.cents <= 0:
            return 0.0
        return round((self.average.cents - self.current.cents) / self.average.cents * 100, 1)


@dataclass(frozen=True, slots=True)
class DiscountAssessment:
    classification: DiscountClass
    evidence: str


@dataclass(frozen=True, slots=True)
class SourceStatus:
    source_id: str
    label: str
    status: Literal["ok", "empty", "error", "timeout", "disabled"]
    items: int = 0
    discarded: int = 0
    discard_reasons: dict[str, int] = field(default_factory=dict)
    duration_ms: int = 0
    error: str | None = None


@dataclass(frozen=True, slots=True)
class OfferView:
    """Oferta enriquecida para apresentacao (não persistida)."""

    offer: Offer
    product: Product
    store: Store
    seller: Seller | None
    stats: PriceStats | None
    discount: DiscountAssessment
    deal_score: float
    flags: tuple[str, ...] = ()
    coupons: tuple[CouponEvaluation, ...] = ()
    best_coupon: CouponEvaluation | None = None
    promotion: Promotion | None = None
    reviews: ReviewSummary | None = None
    score_breakdown: dict[str, float] = field(default_factory=dict)
