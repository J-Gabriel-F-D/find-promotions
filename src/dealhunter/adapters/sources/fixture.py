"""Adapter de demonstração (offline).

Serve para desenvolvimento, testes e para o usuário conhecer a ferramenta sem
rede. Os dados são **fictícios** e sempre marcados como tal: dominio
``demo.local``, ``confidence`` baixa e aviso explícito na saída.
"""

from __future__ import annotations

from dataclasses import dataclass

from dealhunter.adapters.sources.base import Capability
from dealhunter.application.dto import QuerySpec
from dealhunter.domain.models import CollectedOffer
from dealhunter.services.text import detect_brand, normalize_text

DEMO_DOMAIN = "demo.local"


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


# Preços e lojas são fictícios. A série historica existe para exercitar o
# motor de preço e a detecção de desconto sem depender de rede.
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
    ),
)


class FixtureAdapter:
    """Fonte offline determinística, marcada como demonstração."""

    id = "fixture"
    label = "Demonstração (offline)"
    capabilities: frozenset[Capability] = frozenset({"search"})

    def __init__(self, *, catalog: tuple[DemoOffer, ...] = CATALOG) -> None:
        self._catalog = catalog

    async def search(self, spec: QuerySpec) -> list[CollectedOffer]:
        terms = [token for token in normalize_text(spec.search_terms).split() if len(token) > 2]
        results: list[CollectedOffer] = []

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
                    store_domain=DEMO_DOMAIN,
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
                    history=item.history,
                )
            )
        return results
