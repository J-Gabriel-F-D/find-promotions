"""Adapter do Mercado Livre (API publica oficial).

Documentação: https://developers.mercadolivre.com.br
Usa ``/sites/{site}/search``; não faz scraping de HTML. Um token de aplicação e
opcional (aumenta limites), lido de variavel de ambiente ou keyring.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from dealhunter.adapters.http.client import HttpClient
from dealhunter.adapters.sources.base import Capability
from dealhunter.application.dto import QuerySpec
from dealhunter.domain.models import CollectedOffer
from dealhunter.domain.value_objects.money import Money

API_BASE = "https://api.mercadolibre.com"
SITE_BR = "MLB"
STORE_DOMAIN = "mercadolivre.com.br"

# Atributos que valem a pena guardar como especificacao.
_SPEC_ATTRS = {
    "BRAND": "marca",
    "MODEL": "modelo",
    "INTERNAL_MEMORY": "armazenamento",
    "RAM": "memoria_ram",
    "SCREEN_SIZE": "tela",
    "PROCESSOR_MODEL": "processador",
}


def _to_cents(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return Money.from_decimal(Decimal(str(value))).cents
    except (ValueError, TypeError):
        return None


class MercadoLivreAdapter:
    id = "mercadolivre"
    label = "Mercado Livre"
    capabilities: frozenset[Capability] = frozenset({"search", "detail"})

    def __init__(
        self,
        http: HttpClient,
        *,
        access_token: str | None = None,
        site: str = SITE_BR,
        max_results: int = 50,
    ) -> None:
        self._http = http
        self._token = access_token
        self._site = site
        self._max_results = max_results

    async def search(self, spec: QuerySpec) -> list[CollectedOffer]:
        query = spec.search_terms
        params: dict[str, Any] = {"q": query, "limit": min(self._max_results, 50)}
        if spec.max_price_cents is not None:
            params["price"] = f"*-{spec.max_price_cents / 100:.2f}"

        headers = {"Authorization": f"Bearer {self._token}"} if self._token else None
        payload = await self._http.get_json(
            f"{API_BASE}/sites/{self._site}/search", params=params, headers=headers
        )
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            raise ValueError("resposta da API sem lista 'results'")

        offers: list[CollectedOffer] = []
        for item in results:
            offer = self._parse_item(item)
            if offer is not None:
                offers.append(offer)
        return offers

    def _parse_item(self, item: dict[str, Any]) -> CollectedOffer | None:
        title = str(item.get("title") or "").strip()
        permalink = str(item.get("permalink") or "").strip()
        price_cents = _to_cents(item.get("price"))
        if not title or not permalink or price_cents is None:
            return None

        attributes = {
            str(attr.get("id")): str(attr.get("value_name") or "")
            for attr in item.get("attributes") or []
            if isinstance(attr, dict)
        }
        seller = item.get("seller") or {}
        reputation = seller.get("seller_reputation") or {}
        ratings = (reputation.get("transactions") or {}).get("ratings") or {}
        positive = ratings.get("positive")

        shipping = item.get("shipping") or {}
        free_shipping = bool(shipping.get("free_shipping"))

        specs = {
            label: attributes[key] for key, label in _SPEC_ATTRS.items() if attributes.get(key)
        }

        return CollectedOffer(
            source_id=self.id,
            title=title,
            url=permalink,
            source_url=f"{API_BASE}/items/{item.get('id')}",
            price_cents=price_cents,
            list_price_cents=_to_cents(item.get("original_price")),
            shipping_cents=0 if free_shipping else None,
            store_name=str(item.get("official_store_name") or "Mercado Livre"),
            store_domain=STORE_DOMAIN,
            seller_name=str(seller.get("nickname") or seller.get("id") or "") or None,
            # Reputacao oficial e "percentual de positivas"; convertemos para a
            # escala 0-5 apenas para exibicao, preservando a origem.
            seller_rating=round(float(positive) * 5, 2)
            if isinstance(positive, (int, float))
            else None,
            seller_sales=(reputation.get("transactions") or {}).get("total"),
            condition="used" if str(item.get("condition", "")).lower() == "used" else "new",
            availability="in_stock"
            if (item.get("available_quantity") or 0) > 0
            else "out_of_stock",
            brand=attributes.get("BRAND") or None,
            gtin=(attributes.get("GTIN") or "").strip() or None,
            mpn=(attributes.get("MODEL") or "").strip() or None,
            specs=specs,
            confidence=0.95,
        )
