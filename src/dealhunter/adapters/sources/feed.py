"""Adapter generico para feeds JSON de lojas/afiliados.

Não e um scraper de HTML: consome um endpoint que devolve o formato documentado
no README (lista ``offers``). Assim novas lojas entram sem código novo, apenas
configurando a URL -- e sempre respeitando robots.txt do dominio.

Além das ofertas, o feed pode declarar ``coupons`` (por oferta), ``promotion``
(janela promocional) e ``reviews`` (agregado de avaliações). Tudo é tratado como
**declaração da fonte**, nunca como fato validado por nós.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, cast
from urllib.parse import urlsplit

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

_MAX_OFFERS = 500
_MAX_TITLE = 500
_MAX_URL = 2_048
_MAX_STORE = 200
_MAX_SELLER = 200
_MAX_CODE = 100
_MAX_LABEL = 200
_MAX_TEXT = 200
_MAX_SPECS = 50
_DOMAIN = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
# Remove controles C0/C1, DEL, escapes ANSI e controles de direção bidi.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")


def _text(value: Any, *, limit: int) -> str | None:
    """Texto externo saneado; ``None`` quando ausente ou acima do limite."""
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    cleaned = " ".join(_CONTROL.sub("", value).split())
    if len(cleaned) > limit:
        return None
    return cleaned


def _http_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = _CONTROL.sub("", value).strip()
    if not text or len(text) > _MAX_URL:
        return None
    parts = urlsplit(text)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None
    if parts.username or parts.password:
        return None
    return text


def _domain(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = _CONTROL.sub("", value).strip().lower()
    if not text or len(text) > 253:
        return None
    if any(char in text for char in "/:@?# \t"):
        return None
    host = text.strip(".")
    if not host or ".." in host or not _DOMAIN.fullmatch(host):
        return None
    return host


def _cents(value: Any) -> int | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Money.from_decimal(Decimal(value)).cents
    try:
        return Money.parse(str(value)).cents
    except (ValueError, InvalidOperation, TypeError):
        return None


def _int(value: Any) -> int | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
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

            for raw in items[:_MAX_OFFERS]:
                parsed = self._parse(raw, fallback_source=feed_url)
                if parsed is not None:
                    offers.append(parsed)

        if skipped and not offers:
            raise PermissionError("robots.txt não permite acessar: " + ", ".join(skipped))
        return offers

    def _parse(self, raw: Any, *, fallback_source: str) -> CollectedOffer | None:
        if not isinstance(raw, dict):
            return None

        title = _text(raw.get("title"), limit=_MAX_TITLE)
        url = _http_url(raw.get("url"))
        price_cents = _cents(raw.get("price"))
        if not title or not url or price_cents is None or price_cents <= 0:
            return None

        currency = str(raw.get("currency") or "BRL").strip().upper()
        if not _CURRENCY.fullmatch(currency):
            return None

        source_url = _http_url(raw.get("source_url")) or fallback_source
        list_price_cents = _cents(raw.get("list_price"))
        if list_price_cents is not None and list_price_cents <= 0:
            list_price_cents = None
        shipping_cents = _cents(raw.get("shipping"))
        if shipping_cents is not None and shipping_cents < 0:
            shipping_cents = None

        condition_raw = str(raw.get("condition") or "new").strip().lower()
        condition: Condition = (
            cast(Condition, condition_raw)
            if condition_raw in {"new", "used", "refurbished"}
            else "new"
        )

        specs = self._parse_specs(raw.get("specs"))
        brand = _text(raw.get("brand"), limit=_MAX_TEXT) or None
        gtin = _text(raw.get("gtin"), limit=_MAX_TEXT) or None
        mpn = _text(raw.get("mpn"), limit=_MAX_TEXT) or None
        seller_name = _text(raw.get("seller"), limit=_MAX_SELLER) or None
        availability = _text(raw.get("availability"), limit=_MAX_TEXT) or "unknown"

        return CollectedOffer(
            source_id=self.id,
            title=title,
            url=url,
            source_url=source_url,
            price_cents=price_cents,
            currency=currency,
            list_price_cents=list_price_cents,
            shipping_cents=shipping_cents,
            store_name=_text(raw.get("store"), limit=_MAX_STORE) or "Loja",
            store_domain=_domain(raw.get("store_domain")),
            seller_name=seller_name,
            seller_rating=_float(raw.get("seller_rating")),
            condition=condition,
            availability=availability,
            brand=brand,
            gtin=gtin,
            mpn=mpn,
            specs=specs,
            confidence=0.75,
            coupons=self._parse_coupons(raw.get("coupons")),
            promotion=self._parse_promotion(raw.get("promotion")),
            reviews=self._parse_reviews(raw.get("reviews")),
        )

    def _parse_specs(self, raw: Any) -> dict[str, str]:
        if not isinstance(raw, dict):
            return {}
        specs: dict[str, str] = {}
        for key, value in list(raw.items())[:_MAX_SPECS]:
            name = _text(key, limit=_MAX_TEXT)
            text = _text(value, limit=_MAX_TEXT)
            if name and text:
                specs[name] = text
        return specs

    def _parse_coupons(self, raw: Any) -> tuple[CollectedCoupon, ...]:
        if not isinstance(raw, list):
            return ()
        coupons: list[CollectedCoupon] = []
        for item in raw[:20]:
            if not isinstance(item, dict):
                continue
            code = _text(item.get("code"), limit=_MAX_CODE)
            kind = str(item.get("kind") or item.get("type") or "").strip().lower()
            value = _int(item.get("value")) or 0
            if not code or kind not in _COUPON_KINDS:
                continue
            if kind in {"percent", "fixed"} and value <= 0:
                continue
            if kind == "percent" and value > 100:
                continue
            min_purchase = _cents(item.get("min_purchase"))
            max_discount = _cents(item.get("max_discount"))
            if (min_purchase is not None and min_purchase < 0) or (
                max_discount is not None and max_discount < 0
            ):
                continue
            currency = str(item.get("currency") or "BRL").strip().upper()
            if not _CURRENCY.fullmatch(currency):
                continue
            coupons.append(
                CollectedCoupon(
                    code=code,
                    kind=cast(CouponKind, kind),
                    value=value,
                    min_purchase_cents=min_purchase,
                    max_discount_cents=max_discount,
                    valid_from=_datetime(item.get("valid_from")),
                    valid_until=_datetime(item.get("valid_until"), end_of_day=True),
                    currency=currency,
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
        label = _text(raw.get("label"), limit=_MAX_LABEL)
        if label is None:
            return None
        starts_at = _datetime(raw.get("starts_at"))
        ends_at = _datetime(raw.get("ends_at"))
        if starts_at is None and ends_at is None:
            return None
        return CollectedPromotion(
            kind=cast(PromotionKind, kind),
            label=label,
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
