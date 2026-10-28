"""Adapter de demonstração (offline).

Serve para desenvolvimento, testes e para o usuário conhecer a ferramenta sem
rede. Os dados são **fictícios** e sempre marcados como tal: dominio
``demo.local``, ``confidence`` baixa e aviso explícito na saída.

As janelas de promoção são relativas ao relógio injetado, para que a demo
exercite urgência/expiração sem depender da data em que o teste roda.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from dealhunter.adapters.sources.base import Capability
from dealhunter.application.dto import QuerySpec
from dealhunter.domain.models import (
    CollectedCoupon,
    CollectedOffer,
    CollectedPromotion,
    CollectedReviews,
    CouponKind,
    PromotionKind,
)
from dealhunter.domain.ports.clock import Clock, SystemClock
from dealhunter.services.text import detect_brand, normalize_text

DEMO_DOMAIN = "demo.local"


def demo_domain(store: str) -> str:
    """Dominio ficticio por loja, mantendo o sufixo ``demo.local``.

    Um dominio por loja é essencial: ``Store.id`` deriva do dominio, então
    compartilhar ``demo.local`` faria todas as lojas demo colapsarem em uma.
    """
    slug = "-".join(normalize_text(store).split())
    return f"{slug}.{DEMO_DOMAIN}"


@dataclass(frozen=True, slots=True)
class DemoCoupon:
    code: str
    kind: CouponKind
    value: int
    min_purchase_cents: int | None = None
    max_discount_cents: int | None = None
    starts_in_hours: int | None = None
    ends_in_hours: int | None = None


@dataclass(frozen=True, slots=True)
class DemoPromotion:
    kind: PromotionKind
    label: str
    starts_in_hours: int | None = None
    ends_in_hours: int | None = None


@dataclass(frozen=True, slots=True)
class DemoReviews:
    rating: float
    count: int
    distribution: dict[int, int]


@dataclass(frozen=True, slots=True)
class DemoOffer:
    title: str
    store: str
    price_cents: int
    list_price_cents: int | None
    shipping_cents: int
    url: str
    storage_gb: int
    ram_gb: int
    seller: str
    seller_rating: float
    history: tuple[tuple[int, int], ...] = ()
    coupons: tuple[DemoCoupon, ...] = ()
    promotion: DemoPromotion | None = None
    reviews: DemoReviews | None = None


# Preços, cupons, promoções e avaliações são fictícios. A série historica
# existe para exercitar o motor de preço e a detecção de desconto sem rede.
CATALOG: tuple[DemoOffer, ...] = (
    DemoOffer(
        title="Xiaomi Redmi Note 14 256GB 8GB RAM 5G",
        store="Loja Aurora",
        price_cents=164_900,
        list_price_cents=199_900,
        shipping_cents=0,
        url=f"https://{DEMO_DOMAIN}/aurora/redmi-note-14-256",
        storage_gb=256,
        ram_gb=8,
        seller="Aurora Oficial",
        seller_rating=4.8,
        history=((60, 194_900), (30, 189_900), (10, 179_900)),
        coupons=(
            DemoCoupon(
                "AURORA10",
                "percent",
                10,
                min_purchase_cents=150_000,
                max_discount_cents=20_000,
                ends_in_hours=24 * 7,
            ),
        ),
        promotion=DemoPromotion("flash", "Relâmpago Aurora", ends_in_hours=3),
        reviews=DemoReviews(4.7, 213, {5: 160, 4: 38, 3: 9, 2: 4, 1: 2}),
    ),
    DemoOffer(
        title="Xiaomi Redmi Note 14 5G 256 GB 8GB RAM",
        store="MegaTech",
        price_cents=169_990,
        list_price_cents=189_990,
        shipping_cents=1_990,
        url=f"https://{DEMO_DOMAIN}/megatech/redmi-note-14-256",
        storage_gb=256,
        ram_gb=8,
        seller="MegaTech Store",
        seller_rating=4.6,
        history=((60, 197_900), (30, 191_900), (10, 184_900)),
        coupons=(DemoCoupon("MEGA50", "fixed", 5_000, min_purchase_cents=150_000),),
        promotion=DemoPromotion("regular", "Semana MegaTech", ends_in_hours=24 * 5),
        reviews=DemoReviews(4.4, 87, {5: 62, 4: 15, 3: 6, 2: 2, 1: 2}),
    ),
    DemoOffer(
        title="Smartphone Xiaomi Redmi Note 14 256GB",
        store="ImportaFacil",
        price_cents=149_900,
        list_price_cents=249_900,
        shipping_cents=4_900,
        url=f"https://{DEMO_DOMAIN}/importafacil/redmi-note-14-256",
        storage_gb=256,
        ram_gb=8,
        seller="ImportaFacil",
        seller_rating=3.9,
        history=((60, 158_900), (30, 156_900), (10, 152_900)),
        # Mínimo de R$ 2.000 nunca é atingido: demonstra cupom não aplicável.
        coupons=(DemoCoupon("IMP5", "percent", 5, min_purchase_cents=200_000),),
        promotion=DemoPromotion("regular", "Oferta ImportaFacil", ends_in_hours=30),
        reviews=DemoReviews(3.8, 41, {5: 24, 4: 8, 3: 5, 2: 2, 1: 2}),
    ),
    DemoOffer(
        title="Xiaomi Redmi Note 13 128GB 8GB RAM",
        store="Loja Aurora",
        price_cents=129_900,
        list_price_cents=159_900,
        shipping_cents=0,
        url=f"https://{DEMO_DOMAIN}/aurora/redmi-note-13-128",
        storage_gb=128,
        ram_gb=8,
        seller="Aurora Oficial",
        seller_rating=4.8,
        reviews=DemoReviews(4.5, 180, {5: 130, 4: 35, 3: 10, 2: 3, 1: 2}),
    ),
    DemoOffer(
        title="Notebook Lenovo IdeaPad 3 Ryzen 5 16GB RAM SSD 512GB",
        store="Loja Aurora",
        price_cents=349_900,
        list_price_cents=419_900,
        shipping_cents=0,
        url=f"https://{DEMO_DOMAIN}/aurora/ideapad-3-16-512",
        storage_gb=512,
        ram_gb=16,
        seller="Aurora Oficial",
        seller_rating=4.8,
        history=((60, 399_900), (30, 389_900), (10, 369_900)),
        coupons=(
            DemoCoupon("NOTE100", "fixed", 10_000, min_purchase_cents=300_000, ends_in_hours=72),
        ),
        promotion=DemoPromotion("clearance", "Liquidação de notebooks", ends_in_hours=24 * 10),
        reviews=DemoReviews(4.6, 180, {5: 130, 4: 35, 3: 10, 2: 3, 1: 2}),
    ),
    DemoOffer(
        title="Notebook Lenovo IdeaPad 3 16GB 512GB SSD",
        store="MegaTech",
        price_cents=359_900,
        list_price_cents=409_900,
        shipping_cents=2_990,
        url=f"https://{DEMO_DOMAIN}/megatech/ideapad-3-16-512",
        storage_gb=512,
        ram_gb=16,
        seller="MegaTech Store",
        seller_rating=4.6,
        history=((60, 409_900), (30, 394_900), (10, 379_900)),
        # Expirado de propósito: a UI deve mostrar "expirado", nunca aplicar.
        coupons=(DemoCoupon("MEGA10", "percent", 10, ends_in_hours=-24),),
        reviews=DemoReviews(4.4, 95, {5: 60, 4: 20, 3: 9, 2: 4, 1: 2}),
    ),
    DemoOffer(
        title="Notebook Acer Aspire 5 Ryzen 5 8GB RAM 512GB SSD",
        store="MegaTech",
        price_cents=319_900,
        list_price_cents=369_900,
        shipping_cents=1_990,
        url=f"https://{DEMO_DOMAIN}/megatech/aspire-5-8-512",
        storage_gb=512,
        ram_gb=8,
        seller="MegaTech Store",
        seller_rating=4.6,
        coupons=(DemoCoupon("MEGA15", "percent", 15, min_purchase_cents=500_000),),
        reviews=DemoReviews(4.1, 73, {5: 40, 4: 18, 3: 9, 2: 4, 1: 2}),
    ),
    DemoOffer(
        title="Placa de Video NVIDIA GeForce RTX 4070 12GB GDDR6X",
        store="Loja Aurora",
        price_cents=339_900,
        list_price_cents=419_900,
        shipping_cents=0,
        url=f"https://{DEMO_DOMAIN}/aurora/rtx-4070-12gb",
        storage_gb=12,
        ram_gb=0,
        seller="Aurora Oficial",
        seller_rating=4.8,
        history=((60, 409_900), (30, 399_900), (10, 379_900)),
        coupons=(
            DemoCoupon("GAME200", "fixed", 20_000, min_purchase_cents=300_000, ends_in_hours=48),
        ),
        promotion=DemoPromotion("flash", "Relâmpago gamer", ends_in_hours=8),
        reviews=DemoReviews(4.5, 64, {5: 42, 4: 13, 3: 5, 2: 2, 1: 2}),
    ),
    DemoOffer(
        title="Placa de Video RTX 4070 12GB",
        store="ImportaFacil",
        price_cents=319_900,
        list_price_cents=459_900,
        shipping_cents=5_900,
        url=f"https://{DEMO_DOMAIN}/importafacil/rtx-4070-12gb",
        storage_gb=12,
        ram_gb=0,
        seller="ImportaFacil",
        seller_rating=3.9,
        history=((60, 329_900), (30, 326_900), (10, 322_900)),
        reviews=DemoReviews(3.7, 52, {5: 26, 4: 13, 3: 7, 2: 3, 1: 3}),
    ),
    DemoOffer(
        title="Apple iPhone 16 128GB",
        store="Loja Aurora",
        price_cents=429_900,
        list_price_cents=479_900,
        shipping_cents=0,
        url=f"https://{DEMO_DOMAIN}/aurora/iphone-16-128",
        storage_gb=128,
        ram_gb=8,
        seller="Aurora Oficial",
        seller_rating=4.8,
        history=((60, 469_900), (30, 459_900), (10, 449_900)),
        coupons=(
            DemoCoupon(
                "IPHONE5",
                "percent",
                5,
                max_discount_cents=10_000,
                ends_in_hours=24 * 3,
            ),
        ),
        promotion=DemoPromotion("regular", "Semana do iPhone", ends_in_hours=48),
        reviews=DemoReviews(4.8, 512, {5: 400, 4: 70, 3: 25, 2: 10, 1: 7}),
    ),
)


class FixtureAdapter:
    """Fonte offline determinística, marcada como demonstração."""

    id = "fixture"
    label = "Demonstração (offline)"
    capabilities: frozenset[Capability] = frozenset({"search", "coupons", "reviews"})

    def __init__(
        self,
        *,
        catalog: tuple[DemoOffer, ...] = CATALOG,
        clock: Clock | None = None,
    ) -> None:
        self._catalog = catalog
        self._clock = clock or SystemClock()

    async def search(self, spec: QuerySpec) -> list[CollectedOffer]:
        terms = [token for token in normalize_text(spec.search_terms).split() if len(token) > 2]
        results: list[CollectedOffer] = []
        now = self._clock.now()

        for item in self._catalog:
            haystack = normalize_text(item.title)
            if terms and not any(term in haystack for term in terms):
                continue
            if spec.brand and detect_brand(item.title) != spec.brand:
                continue
            if spec.storage_gb and item.storage_gb != spec.storage_gb:
                continue
            if spec.ram_gb and item.ram_gb and item.ram_gb < spec.ram_gb:
                continue
            if spec.max_price_cents and item.price_cents > spec.max_price_cents:
                continue

            results.append(
                CollectedOffer(
                    source_id=self.id,
                    title=item.title,
                    url=item.url,
                    source_url=item.url,
                    price_cents=item.price_cents,
                    list_price_cents=item.list_price_cents,
                    shipping_cents=item.shipping_cents,
                    store_name=item.store,
                    store_domain=demo_domain(item.store),
                    seller_name=item.seller,
                    seller_rating=item.seller_rating,
                    condition="new",
                    availability="in_stock",
                    brand=detect_brand(item.title),
                    specs={
                        "armazenamento": f"{item.storage_gb}GB",
                        "memoria_ram": f"{item.ram_gb}GB" if item.ram_gb else "-",
                    },
                    confidence=0.4,
                    collected_at=now,
                    history=item.history,
                    coupons=tuple(
                        CollectedCoupon(
                            code=coupon.code,
                            kind=coupon.kind,
                            value=coupon.value,
                            min_purchase_cents=coupon.min_purchase_cents,
                            max_discount_cents=coupon.max_discount_cents,
                            valid_from=(
                                now + timedelta(hours=coupon.starts_in_hours)
                                if coupon.starts_in_hours is not None
                                else None
                            ),
                            valid_until=(
                                now + timedelta(hours=coupon.ends_in_hours)
                                if coupon.ends_in_hours is not None
                                else None
                            ),
                            confidence=0.4,
                        )
                        for coupon in item.coupons
                    ),
                    promotion=(
                        CollectedPromotion(
                            kind=item.promotion.kind,
                            label=item.promotion.label,
                            starts_at=(
                                now + timedelta(hours=item.promotion.starts_in_hours)
                                if item.promotion.starts_in_hours is not None
                                else None
                            ),
                            ends_at=(
                                now + timedelta(hours=item.promotion.ends_in_hours)
                                if item.promotion.ends_in_hours is not None
                                else None
                            ),
                            confidence=0.4,
                        )
                        if item.promotion is not None
                        else None
                    ),
                    reviews=(
                        CollectedReviews(
                            rating=item.reviews.rating,
                            count=item.reviews.count,
                            distribution=dict(item.reviews.distribution),
                            confidence=0.4,
                        )
                        if item.reviews is not None
                        else None
                    ),
                )
            )
        return results
