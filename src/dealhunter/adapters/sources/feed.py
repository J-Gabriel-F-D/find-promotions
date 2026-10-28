"""Adapter generico para feeds JSON de lojas/afiliados.

Não e um scraper de HTML: consome um endpoint que devolve o formato documentado
no README (lista ``offers``). Assim novas lojas entram sem código novo, apenas
configurando a URL -- e sempre respeitando robots.txt do dominio.

Além das ofertas, o feed pode declarar ``coupons`` (por oferta), ``promotion``
(janela promocional) e ``reviews`` (agregado de avaliações). Tudo é tratado como
**declaração da fonte**, nunca como fato validado por nós.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from dealhunter.adapters.http.client import HttpClient
from dealhunter.adapters.http.robots import RobotsGuard
from dealhunter.adapters.sources.base import Capability
from dealhunter.application.dto import QuerySpec
from dealhunter.domain.models import (
    CollectedCoupon,
    CollectedOffer,
    CollectedPromotion,
    CollectedReviews,
    Condition,
    CouponKind,
    PromotionKind,
)
from dealhunter.domain.value_objects.money import Money

_COUPON_KINDS: set[str] = {"percent", "fixed", "free_shipping"}
_PROMOTION_KINDS: set[str] = {"flash", "regular", "clearance"}


def _cents(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return Money.from_decimal(Decimal(value)).cents
    try:
        return Money.parse(str(value)).cents
    except (ValueError, InvalidOperation):
        return None


def _int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _datetime(value: Any, *, end_of_day: bool = False) -> datetime | None:
    """Interpreta ISO-8601 (com ou sem fuso) ou ``AAAA-MM-DD``.

    Datas sem fuso são assumidas UTC. Data pura em ``valid_until`` vale até o
    fim do dia, que é a leitura usual de "válido até 31/12".
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if len(text) == 10:
        text += "T23:59:59" if end_of_day else "T00:00:00"
    elif text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class FeedAdapter:
    id = "feed"
    label = "Feed JSON"
    capabilities: frozenset[Capability] = frozenset({"search", "coupons", "reviews"})

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
            seller_rating=_float(raw.get("seller_rating")),
            condition=condition,
            availability=str(raw.get("availability") or "unknown"),
            brand=raw.get("brand"),
            gtin=raw.get("gtin"),
            mpn=raw.get("mpn"),
            specs={str(key): str(value) for key, value in specs.items()},
            confidence=0.75,
            coupons=self._parse_coupons(raw.get("coupons")),
            promotion=self._parse_promotion(raw.get("promotion")),
            reviews=self._parse_reviews(raw.get("reviews")),
        )

    def _parse_coupons(self, raw: Any) -> tuple[CollectedCoupon, ...]:
        if not isinstance(raw, list):
            return ()
        coupons: list[CollectedCoupon] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code") or "").strip()
            kind = str(item.get("kind") or item.get("type") or "").strip().lower()
            value = _int(item.get("value")) or 0
            if not code or kind not in _COUPON_KINDS:
                continue
            if kind in {"percent", "fixed"} and value <= 0:
                continue
            coupons.append(
                CollectedCoupon(
                    code=code,
                    kind=cast(CouponKind, kind),
                    value=value,
                    min_purchase_cents=_cents(item.get("min_purchase")),
                    max_discount_cents=_cents(item.get("max_discount")),
                    valid_from=_datetime(item.get("valid_from")),
                    valid_until=_datetime(item.get("valid_until"), end_of_day=True),
                    currency=str(item.get("currency") or "BRL").upper(),
                    confidence=0.6,
                )
            )
        return tuple(coupons)

    def _parse_promotion(self, raw: Any) -> CollectedPromotion | None:
        if not isinstance(raw, dict):
            return None
        kind = str(raw.get("kind") or raw.get("type") or "regular").strip().lower()
        if kind not in _PROMOTION_KINDS:
            kind = "regular"
        starts_at = _datetime(raw.get("starts_at"))
        ends_at = _datetime(raw.get("ends_at"))
        if starts_at is None and ends_at is None:
            return None
        return CollectedPromotion(
            kind=cast(PromotionKind, kind),
            label=str(raw.get("label") or ""),
            starts_at=starts_at,
            ends_at=ends_at,
            confidence=0.6,
        )

    def _parse_reviews(self, raw: Any) -> CollectedReviews | None:
        if not isinstance(raw, dict):
            return None
        rating = _float(raw.get("rating"))
        count = _int(raw.get("count"))
        if rating is None or count is None or count <= 0 or not 0 <= rating <= 5:
            return None
        distribution: dict[int, int] = {}
        raw_distribution = raw.get("distribution")
        if isinstance(raw_distribution, dict):
            for score, value in raw_distribution.items():
                try:
                    key, amount = int(score), int(value)
                except (TypeError, ValueError):
                    continue
                if 1 <= key <= 5 and amount >= 0:
                    distribution[key] = amount
        return CollectedReviews(
            rating=rating,
            count=count,
            distribution=distribution,
            confidence=0.6,
        )
