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

    @property
    def price(self) -> Money:
        return Money(self.price_cents, self.currency)


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
