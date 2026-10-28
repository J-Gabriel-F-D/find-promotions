"""Adapter generico para feeds JSON de lojas/afiliados.

Não e um scraper de HTML: consome um endpoint que devolve o formato documentado
no README (lista ``offers``). Assim novas lojas entram sem código novo, apenas
configurando a URL -- e sempre respeitando robots.txt do dominio.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, cast

from dealhunter.adapters.http.client import HttpClient
from dealhunter.adapters.http.robots import RobotsGuard
from dealhunter.adapters.sources.base import Capability
from dealhunter.application.dto import QuerySpec
from dealhunter.domain.models import CollectedOffer, Condition
from dealhunter.domain.value_objects.money import Money


def _cents(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return Money.from_decimal(Decimal(value)).cents
    try:
        return Money.parse(str(value)).cents
    except (ValueError, InvalidOperation):
        return None


class FeedAdapter:
    id = "feed"
    label = "Feed JSON"
    capabilities: frozenset[Capability] = frozenset({"search"})

    def __init__(
        self,
        http: HttpClient,
        urls: list[str],
        *,
        robots: RobotsGuard | None = None,
    ) -> None:
        self._http = http
        self._urls = list(urls)
        self._robots = robots

    async def search(self, spec: QuerySpec) -> list[CollectedOffer]:
        offers: list[CollectedOffer] = []
        skipped: list[str] = []

        for feed_url in self._urls:
            if self._robots is not None and not await self._robots.allowed(feed_url):
                skipped.append(feed_url)
                continue

            payload = await self._http.get_json(feed_url)
            items = payload.get("offers") if isinstance(payload, dict) else None
            if not isinstance(items, list):
                raise ValueError(f"feed sem lista 'offers': {feed_url}")

            for raw in items:
                parsed = self._parse(raw, fallback_source=feed_url)
                if parsed is not None:
                    offers.append(parsed)

        if skipped and not offers:
            raise PermissionError("robots.txt não permite acessar: " + ", ".join(skipped))
        return offers

    def _parse(self, raw: Any, *, fallback_source: str) -> CollectedOffer | None:
        if not isinstance(raw, dict):
            return None

        title = str(raw.get("title") or "").strip()
        url = str(raw.get("url") or "").strip()
        price_cents = _cents(raw.get("price"))
        if not title or not url or price_cents is None:
            return None

        condition_raw = str(raw.get("condition") or "new").lower()
        condition: Condition = (
            cast(Condition, condition_raw)
            if condition_raw in {"new", "used", "refurbished"}
            else "new"
        )

        specs_raw = raw.get("specs")
        specs: dict[object, object] = specs_raw if isinstance(specs_raw, dict) else {}

        return CollectedOffer(
            source_id=self.id,
            title=title,
            url=url,
            source_url=str(raw.get("source_url") or fallback_source),
            price_cents=price_cents,
            currency=str(raw.get("currency") or "BRL").upper(),
            list_price_cents=_cents(raw.get("list_price")),
            shipping_cents=_cents(raw.get("shipping")),
            store_name=str(raw.get("store") or "Loja"),
            store_domain=raw.get("store_domain"),
            seller_name=raw.get("seller"),
            seller_rating=raw.get("seller_rating"),
            condition=condition,
            availability=str(raw.get("availability") or "unknown"),
            brand=raw.get("brand"),
            gtin=raw.get("gtin"),
            mpn=raw.get("mpn"),
            specs={str(key): str(value) for key, value in specs.items()},
            confidence=0.75,
        )
