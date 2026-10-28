"""Testes dos adapters de coleta."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from dealhunter.adapters.http.client import HttpClient
from dealhunter.adapters.sources.feed import FeedAdapter
from dealhunter.adapters.sources.fixture import FixtureAdapter
from dealhunter.adapters.sources.mercadolivre import MercadoLivreAdapter
from dealhunter.application.dto import QuerySpec

ML_PAYLOAD = {
    "site_id": "MLB",
    "results": [
        {
            "id": "MLB123",
            "title": "Xiaomi Redmi Note 14 256GB 8GB RAM 5G",
            "condition": "new",
            "permalink": "https://produto.mercadolivre.com.br/MLB-123",
            "price": 1649.0,
            "original_price": 1999.0,
            "available_quantity": 12,
            "shipping": {"free_shipping": True},
            "seller": {
                "id": 999,
                "nickname": "LOJA OFICIAL",
                "seller_reputation": {
                    "transactions": {"total": 5000, "ratings": {"positive": 0.98}}
                },
            },
            "attributes": [
                {"id": "BRAND", "value_name": "Xiaomi"},
                {"id": "MODEL", "value_name": "Redmi Note 14"},
                {"id": "GTIN", "value_name": "7891234567895"},
                {"id": "INTERNAL_MEMORY", "value_name": "256 GB"},
            ],
        },
        {
            "id": "MLB404",
            "title": "Item sem preco",
            "permalink": "https://produto.mercadolivre.com.br/MLB-404",
        },
    ],
}


def _run_ml(payload: dict) -> list:
    async def run() -> list:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload)

        client = HttpClient(
            user_agent="test",
            transport=httpx.MockTransport(handler),
            retry_delay=0,
            guard_urls=False,
        )
        try:
            adapter = MercadoLivreAdapter(client)
            return await adapter.search(QuerySpec(product="redmi note 14", max_price_cents=200_000))
        finally:
            await client.aclose()

    return asyncio.run(run())


class TestMercadoLivre:
    def test_mapeia_campos_da_api(self) -> None:
        offers = _run_ml(ML_PAYLOAD)
        assert len(offers) == 1

        offer = offers[0]
        assert offer.price_cents == 164_900
        assert offer.list_price_cents == 199_900
        assert offer.shipping_cents == 0
        assert offer.condition == "new"
        assert offer.availability == "in_stock"
        assert offer.brand == "Xiaomi"
        assert offer.gtin == "7891234567895"
        assert offer.seller_name == "LOJA OFICIAL"
        assert offer.seller_rating == pytest.approx(4.9)
        assert offer.confidence >= 0.9

    def test_ignora_item_sem_preco(self) -> None:
        offers = _run_ml(ML_PAYLOAD)
        assert all(offer.title != "Item sem preco" for offer in offers)

    def test_resposta_sem_results_falha(self) -> None:
        with pytest.raises(ValueError):
            _run_ml({"site_id": "MLB"})

    def test_sem_token_nao_envia_authorization(self) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(dict(request.headers))
            return httpx.Response(200, json={"results": []})

        async def run() -> None:
            client = HttpClient(
                user_agent="test",
                transport=httpx.MockTransport(handler),
                retry_delay=0,
                guard_urls=False,
            )
            try:
                await MercadoLivreAdapter(client).search(QuerySpec(product="x"))
            finally:
                await client.aclose()

        asyncio.run(run())
        assert "authorization" not in seen


FEED_PAYLOAD = {
    "offers": [
        {
            "title": "Xiaomi Redmi Note 14 256GB",
            "url": "https://loja.example/produto/1",
            "price": "1649.90",
            "list_price": "1999.00",
            "shipping": "0",
            "store": "Loja Exemplo",
            "store_domain": "loja.example",
            "seller": "Loja Exemplo Oficial",
            "seller_rating": 4.7,
            "brand": "Xiaomi",
            "gtin": "7891234567895",
            "condition": "NEW",
            "specs": {"memoria_ram": "8GB"},
        },
        {"title": "Item quebrado", "url": "https://loja.example/2", "price": ""},
    ]
}


def _run_feed(payload: dict, *, robots: object | None = None) -> list:
    async def run() -> list:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload)

        client = HttpClient(
            user_agent="test",
            transport=httpx.MockTransport(handler),
            retry_delay=0,
            guard_urls=False,
        )
        try:
            adapter = FeedAdapter(client, ["https://loja.example/ofertas.json"], robots=robots)
            return await adapter.search(QuerySpec(product="redmi"))
        finally:
            await client.aclose()

    return asyncio.run(run())


class TestFeed:
    def test_mapeia_offers_do_json(self) -> None:
        offers = _run_feed(FEED_PAYLOAD)
        assert len(offers) == 1

        offer = offers[0]
        assert offer.price_cents == 164_990
        assert offer.list_price_cents == 199_900
        assert offer.shipping_cents == 0
        assert offer.condition == "new"
        assert offer.store_domain == "loja.example"
        assert offer.specs["memoria_ram"] == "8GB"
        assert offer.confidence == 0.75

    def test_item_sem_preco_e_ignorado(self) -> None:
        offers = _run_feed(FEED_PAYLOAD)
        assert all(offer.title != "Item quebrado" for offer in offers)

    def test_feed_sem_lista_offers_falha(self) -> None:
        with pytest.raises(ValueError):
            _run_feed({"data": []})

    def test_robots_bloqueado_falha_sem_coletar(self) -> None:
        class RobotsFake:
            async def allowed(self, _url: str) -> bool:
                return False

        with pytest.raises(PermissionError):
            _run_feed(FEED_PAYLOAD, robots=RobotsFake())


def test_feed_declara_cupons_promocao_e_avaliacoes() -> None:
    payload = {
        "offers": [
            {
                "title": "Xiaomi Redmi Note 14 256GB",
                "url": "https://loja.example/produto/1",
                "price": "1649.90",
                "store": "Loja Exemplo",
                "store_domain": "loja.example",
                "coupons": [
                    {
                        "code": "BEMVINDO10",
                        "kind": "percent",
                        "value": 10,
                        "min_purchase": "1500",
                        "valid_until": "2026-12-31",
                    },
                    {"code": "INVALIDO", "kind": "percent", "value": 0},
                    {"code": "", "kind": "fixed", "value": 5},
                ],
                "promotion": {
                    "kind": "flash",
                    "label": "Relâmpago",
                    "ends_at": "2026-03-16T12:00:00Z",
                },
                "reviews": {
                    "rating": 4.6,
                    "count": 100,
                    "distribution": {"5": 80, "4": 15, "1": 2},
                },
            }
        ]
    }
    offers = _run_feed(payload)
    assert len(offers) == 1
    offer = offers[0]

    assert len(offer.coupons) == 1
    coupon = offer.coupons[0]
    assert coupon.code == "BEMVINDO10"
    assert coupon.kind == "percent"
    assert coupon.value == 10
    assert coupon.min_purchase_cents == 150_000
    assert coupon.valid_until is not None
    assert coupon.valid_until.hour == 23
    assert coupon.valid_until.minute == 59

    assert offer.promotion is not None
    assert offer.promotion.kind == "flash"
    assert offer.promotion.ends_at is not None

    assert offer.reviews is not None
    assert offer.reviews.rating == 4.6
    assert offer.reviews.count == 100
    assert offer.reviews.distribution == {5: 80, 4: 15, 1: 2}


def test_feed_sem_cupom_valido_nao_quebra() -> None:
    payload = {
        "offers": [
            {
                "title": "Produto",
                "url": "https://loja.example/p",
                "price": 100,
                "coupons": [{"code": "X", "kind": "desconhecido", "value": 1}],
                "reviews": {"rating": 9, "count": 10},
            }
        ]
    }
    offers = _run_feed(payload)
    assert len(offers) == 1
    assert offers[0].coupons == ()
    assert offers[0].reviews is None


class TestFixture:
    def test_filtra_por_capacidade(self) -> None:
        offers = asyncio.run(FixtureAdapter().search(QuerySpec(product="redmi", storage_gb=256)))
        assert offers
        assert all("256" in offer.title for offer in offers)

    def test_filtra_por_preco(self) -> None:
        offers = asyncio.run(
            FixtureAdapter().search(QuerySpec(product="redmi", max_price_cents=160_000))
        )
        assert offers
        assert all(offer.price_cents <= 160_000 for offer in offers)

    def test_sem_correspondencia_retorna_vazio(self) -> None:
        offers = asyncio.run(FixtureAdapter().search(QuerySpec(product="geladeira inox")))
        assert offers == []

    def test_dados_sao_marcados_como_demonstracao(self) -> None:
        offers = asyncio.run(FixtureAdapter().search(QuerySpec(product="redmi")))
        assert offers
        assert all(
            offer.store_domain and offer.store_domain.endswith(".demo.local") for offer in offers
        )
        assert all(offer.confidence <= 0.4 for offer in offers)
