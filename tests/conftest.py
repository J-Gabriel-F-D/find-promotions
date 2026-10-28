"""Fixtures compartilhadas."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dealhunter.adapters.storage.database import Database
from dealhunter.adapters.storage.repository import OfferRecord
from dealhunter.domain.models import Offer, Product, Seller, Store
from dealhunter.domain.ports.clock import FrozenClock
from dealhunter.domain.value_objects.money import Money
from dealhunter.runtime.paths import AppPaths, resolve_paths


@pytest.fixture()
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[AppPaths]:
    """Isola config/dados/logs em um diretorio temporario."""
    home = tmp_path / "home"
    monkeypatch.setenv("DEALHUNTER_HOME", str(home))
    paths = resolve_paths()
    paths.ensure_directories()
    yield paths


@pytest.fixture()
def database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "dealhunter.db")
    database.migrate()
    return database


@pytest.fixture()
def clock() -> FrozenClock:
    return FrozenClock(datetime(2026, 3, 15, 12, 0, tzinfo=UTC))


@pytest.fixture()
def make_offer_record():
    """Fabricante de ``OfferRecord`` para testes de persistencia."""
    return make_record


def make_record(
    *,
    price_cents: int,
    title: str = "Xiaomi Redmi Note 14 256GB 8GB RAM",
    url: str = "https://loja.example/redmi",
    source: str = "fixture",
    store_name: str = "Loja Teste",
    store_domain: str | None = "loja.example",
    shipping_cents: int | None = 0,
    list_price_cents: int | None = None,
    seller_name: str | None = "Vendedor Teste",
    seller_rating: float | None = 4.5,
    identity: tuple[str, str] = ("model", "xiaomi|redmi note 14|256|ram8"),
) -> OfferRecord:
    """Monta um ``OfferRecord`` consistente para testes de persistencia."""
    product = Product(
        title=title,
        brand="xiaomi",
        family="redmi note 14",
        storage_gb=256,
        ram_gb=8,
        identity_kind=identity[0],
        identity_value=identity[1],
    )
    store = Store(name=store_name, domain=store_domain, source=source)
    seller = (
        Seller(name=seller_name, store_id=store.id, rating=seller_rating, source=source)
        if seller_name
        else None
    )
    offer = Offer(
        product_id=product.id,
        store_id=store.id,
        seller_id=seller.id if seller else None,
        url=url,
        source=source,
        source_url=url,
        price=Money(price_cents),
        list_price=Money(list_price_cents) if list_price_cents else None,
        shipping=Money(shipping_cents) if shipping_cents is not None else None,
        confidence=0.9,
    )
    return OfferRecord(product=product, store=store, seller=seller, offer=offer)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Aplica marcadores por diretório para permitir ``pytest -m security``."""
    markers = {
        "security": "security",
        "integration": "integration",
        "e2e": "e2e",
        "functional": "functional",
        "regression": "regression",
    }
    for item in items:
        path_parts = set(item.path.parts)
        for marker, directory in markers.items():
            if directory in path_parts:
                item.add_marker(getattr(pytest.mark, marker))
