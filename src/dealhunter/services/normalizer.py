"""Normalização de ofertas coletadas em entidades de dominio.

Este e o ponto onde "Samsung Galaxy X 256GB" e "Galaxy X 5G 256 GB" passam a
ser o mesmo produto -- mas somente quando ha evidencia (GTIN, MPN ou
marca+modelo+capacidade). Caso contrario, cada titulo vira um produto proprio.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from dealhunter.domain.models import (
    CollectedOffer,
    Coupon,
    Offer,
    Product,
    Promotion,
    ReviewSummary,
    Seller,
    Store,
)
from dealhunter.domain.value_objects.money import Money
from dealhunter.services.text import (
    build_identity,
    detect_brand,
    infer_ram_gb,
    model_family,
    parse_ram_gb,
    parse_storage_gb,
)


class ProductNormalizer:
    """Converte ofertas cruas em ``Product``/``Store``/``Seller``/``Offer``."""

    def to_product(self, collected: CollectedOffer) -> Product:
        brand = collected.brand or detect_brand(collected.title)
        storage = _spec_int(collected.specs, "armazenamento") or parse_storage_gb(collected.title)
        ram = (
            _spec_int(collected.specs, "memoria_ram")
            or parse_ram_gb(collected.title)
            or infer_ram_gb(collected.title, storage)
        )
        family = model_family(collected.title, brand)
        kind, value = build_identity(
            title=collected.title,
            brand=brand,
            storage_gb=storage,
            ram_gb=ram,
            gtin=collected.gtin,
            mpn=collected.mpn,
        )

        return Product(
            title=collected.title,
            brand=brand,
            model=collected.mpn,
            family=family,
            storage_gb=storage,
            ram_gb=ram,
            gtin=collected.gtin,
            mpn=collected.mpn,
            condition=collected.condition,
            identity_kind=kind,
            identity_value=value,
            specs=dict(collected.specs),
        )

    def to_store(self, collected: CollectedOffer) -> Store:
        return Store(
            name=collected.store_name or collected.store_domain or "Loja desconhecida",
            domain=collected.store_domain,
            source=collected.source_id,
        )

    def to_seller(self, collected: CollectedOffer, store: Store) -> Seller | None:
        if not collected.seller_name:
            return None
        return Seller(
            name=collected.seller_name,
            store_id=store.id,
            rating=collected.seller_rating,
            sales_count=collected.seller_sales,
            source=collected.source_id,
        )

    def to_offer(
        self,
        collected: CollectedOffer,
        *,
        product: Product,
        store: Store,
        seller: Seller | None,
    ) -> Offer:
        currency = collected.currency or "BRL"
        installment_value = (
            Money(collected.installment_cents, currency) if collected.installment_cents else None
        )
        offer = Offer(
            product_id=product.id,
            store_id=store.id,
            seller_id=seller.id if seller else None,
            url=collected.url,
            source=collected.source_id,
            source_url=collected.source_url,
            price=Money(collected.price_cents, currency),
            list_price=Money(collected.list_price_cents, currency)
            if collected.list_price_cents
            else None,
            shipping=Money(collected.shipping_cents, currency)
            if collected.shipping_cents is not None
            else None,
            installments=collected.installments,
            installment_value=installment_value,
            condition=collected.condition,
            availability=collected.availability,
            coupon_code=collected.coupon_code,
            collected_at=collected.collected_at,
            confidence=collected.confidence,
        )
        return replace(offer)

    def to_coupons(
        self, collected: CollectedOffer, *, store: Store, now: datetime
    ) -> tuple[Coupon, ...]:
        """Converte cupons declarados; nunca os marca como validados."""
        coupons: list[Coupon] = []
        for raw in collected.coupons:
            if not raw.code.strip():
                continue
            coupons.append(
                Coupon(
                    store_id=store.id,
                    code=raw.code,
                    kind=raw.kind,
                    value=raw.value,
                    source=collected.source_id,
                    source_url=collected.source_url,
                    min_purchase=Money(raw.min_purchase_cents, raw.currency)
                    if raw.min_purchase_cents is not None
                    else None,
                    max_discount=Money(raw.max_discount_cents, raw.currency)
                    if raw.max_discount_cents is not None
                    else None,
                    valid_from=raw.valid_from,
                    valid_until=raw.valid_until,
                    # Uma declaração da fonte não é verificação: `last_verified_at`
                    # permanece nulo até consultarmos a loja.
                    collected_at=collected.collected_at or now,
                    confidence=raw.confidence,
                )
            )
        return tuple(coupons)

    def to_promotion(self, collected: CollectedOffer, *, offer: Offer) -> Promotion | None:
        raw = collected.promotion
        if raw is None:
            return None
        return Promotion(
            offer_id=offer.id,
            kind=raw.kind,
            label=raw.label,
            source=collected.source_id,
            source_url=collected.source_url,
            starts_at=raw.starts_at,
            ends_at=raw.ends_at,
            collected_at=collected.collected_at,
            confidence=raw.confidence,
        )

    def to_reviews(
        self, collected: CollectedOffer, *, product: Product, store: Store
    ) -> ReviewSummary | None:
        raw = collected.reviews
        if raw is None or raw.count <= 0 or not 0 <= raw.rating <= 5:
            return None
        distribution = {
            int(score): int(count)
            for score, count in raw.distribution.items()
            if 1 <= int(score) <= 5 and int(count) >= 0
        }
        return ReviewSummary(
            product_id=product.id,
            store_id=store.id,
            rating_avg=round(raw.rating, 2),
            rating_count=raw.count,
            source=collected.source_id,
            source_url=collected.source_url,
            distribution=distribution,
            collected_at=collected.collected_at,
            confidence=raw.confidence,
        )


def _spec_int(specs: dict[str, str], key: str) -> int | None:
    raw = specs.get(key)
    if not raw:
        return None
    digits = "".join(char for char in raw if char.isdigit())
    return int(digits) if digits else None
