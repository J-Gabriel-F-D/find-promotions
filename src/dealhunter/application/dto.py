"""DTOs da camada de aplicação."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dealhunter.domain.models import OfferView, PriceStats, SourceStatus
from dealhunter.domain.value_objects.money import Money

SortMode = Literal["best", "price", "reputation"]
ConditionFilter = Literal["new", "used", "any"]


class QuerySpec(BaseModel):
    """Requisitos estruturados, seja vindos de flags ou de linguagem natural."""

    model_config = ConfigDict(extra="forbid")

    raw: str = ""
    product: str = ""
    brand: str | None = None
    model: str | None = None
    category: str | None = None

    max_price_cents: int | None = Field(default=None, ge=0)
    min_price_cents: int | None = Field(default=None, ge=0)
    max_shipping_cents: int | None = Field(default=None, ge=0)

    storage_gb: int | None = Field(default=None, gt=0, le=8192)
    ram_gb: int | None = Field(default=None, gt=0, le=512)
    screen_max_inches: float | None = Field(default=None, gt=0, le=100)
    min_rating: float | None = Field(default=None, ge=0, le=5)

    condition: ConditionFilter = "new"
    stores: list[str] = Field(default_factory=list)
    exclude_stores: list[str] = Field(default_factory=list)

    sort: SortMode = "best"
    limit: int = Field(default=20, ge=1, le=200)

    @field_validator("brand", "model", "category", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _check_price_range(self) -> QuerySpec:
        if (
            self.min_price_cents is not None
            and self.max_price_cents is not None
            and self.min_price_cents > self.max_price_cents
        ):
            raise ValueError("preço mínimo não pode ser maior que o preço máximo")
        return self

    @property
    def max_price(self) -> Money | None:
        return Money(self.max_price_cents) if self.max_price_cents is not None else None

    @property
    def search_terms(self) -> str:
        """Texto enviado aos adapters (curto e sem ruido)."""
        if self.product.strip():
            parts = [self.product.strip()]
        else:
            parts = [part for part in (self.brand, self.category) if part]
            if self.storage_gb:
                parts.append(f"{self.storage_gb}GB")
        return " ".join(parts).strip()

    def summary(self) -> list[str]:
        lines: list[str] = []
        if self.product:
            lines.append(f"Produto: {self.product}")
        if self.brand:
            lines.append(f"Marca: {self.brand.title()}")
        if self.category:
            lines.append(f"Categoria: {self.category}")
        if self.storage_gb:
            lines.append(f"Armazenamento: {self.storage_gb} GB")
        if self.ram_gb:
            lines.append(f"Memória RAM: {self.ram_gb} GB")
        if self.screen_max_inches:
            lines.append(f'Tela: até {self.screen_max_inches:g}"')
        if self.max_price_cents is not None:
            lines.append(f"Preço máximo: {Money(self.max_price_cents)}")
        if self.min_price_cents is not None:
            lines.append(f"Preço mínimo: {Money(self.min_price_cents)}")
        if self.condition != "new":
            lines.append(f"Condição: {self.condition}")
        if self.exclude_stores:
            lines.append(f"Lojas bloqueadas: {', '.join(self.exclude_stores)}")
        return lines


@dataclass(frozen=True, slots=True)
class SearchReport:
    spec: QuerySpec
    views: tuple[OfferView, ...]
    sources: tuple[SourceStatus, ...]
    collected: int
    discarded: int
    discard_reasons: dict[str, int]
    picks: dict[str, str | None]
    warnings: tuple[str, ...] = ()
    started_at: str = ""
    duration_ms: int = 0

    @property
    def found(self) -> bool:
        return bool(self.views)


@dataclass(frozen=True, slots=True)
class PriceSample:
    collected_at: datetime
    price_cents: int
    source: str


@dataclass(frozen=True, slots=True)
class OfferRow:
    """Linha de leitura: oferta + snapshot mais recente + loja/vendedor."""

    offer_id: str
    product_id: str
    title: str
    store_name: str
    store_domain: str | None
    seller_name: str | None
    seller_rating: float | None
    url: str
    price_cents: int
    shipping_cents: int | None
    currency: str
    collected_at: str
    source: str
    source_url: str
    confidence: float


@dataclass(frozen=True, slots=True)
class StoredAlert:
    id: int
    label: str
    query: str
    spec_json: str
    max_price_cents: int | None
    min_discount_pct: float | None
    channels: tuple[str, ...]
    active: bool
    created_at: str
    last_checked_at: str | None


@dataclass(frozen=True, slots=True)
class HistoryPoint:
    collected_at: str
    price: Money
    source: str


@dataclass(frozen=True, slots=True)
class HistoryReport:
    product_id: str
    product_title: str
    points: tuple[HistoryPoint, ...]
    stats: PriceStats | None
    offers: tuple[OfferRow, ...]
    days: int
    warnings: tuple[str, ...] = field(default_factory=tuple)
