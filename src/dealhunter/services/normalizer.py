"""Normalização de ofertas coletadas em entidades de dominio.

Este e o ponto onde "Samsung Galaxy X 256GB" e "Galaxy X 5G 256 GB" passam a
ser o mesmo produto -- mas somente quando ha evidencia (GTIN, MPN ou
marca+modelo+capacidade). Caso contrario, cada titulo vira um produto proprio.
"""

from __future__ import annotations

from dataclasses import replace

from dealhunter.domain.models import CollectedOffer, Offer, Product, Seller, Store
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


def _spec_int(specs: dict[str, str], key: str) -> int | None:
    raw = specs.get(key)
    if not raw:
        return None
    digits = "".join(char for char in raw if char.isdigit())
    return int(digits) if digits else None
