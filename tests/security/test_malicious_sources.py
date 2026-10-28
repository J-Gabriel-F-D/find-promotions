"""Dados externos são não confiáveis: feeds hostis e campos malformados."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from dealhunter.adapters.http.client import HttpClient, HttpError
from dealhunter.adapters.sources.feed import FeedAdapter
from dealhunter.application.dto import QuerySpec

FEED_URL = "https://feed.example/ofertas.json"


def _run(payload: Any) -> list:
    async def go() -> list:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload)

        client = HttpClient(
            user_agent="test",
            transport=httpx.MockTransport(handler),
            retry_delay=0,
            guard_urls=False,
        )
        try:
            return await FeedAdapter(client, [FEED_URL]).search(QuerySpec(product="redmi"))
        finally:
            await client.aclose()

    return asyncio.run(go())


def _offer(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "title": "Xiaomi Redmi Note 14 256GB",
        "url": "https://loja.example/produto/1",
        "price": "1649.90",
        "store": "Loja Exemplo",
        "store_domain": "loja.example",
    }
    base.update(overrides)
    return base


class TestMaliciousUrls:
    @pytest.mark.parametrize(
        "url",
        [
            "javascript:alert(1)",
            "file:///etc/passwd",
            "data:text/html,<script>alert(1)</script>",
            "https://user:pass@loja.example/produto",
            "https:///sem-host",
            "",
        ],
    )
    def test_url_invalida_descarta_oferta(self, url: str) -> None:
        assert _run({"offers": [_offer(url=url)]}) == []

    def test_source_url_maliciosa_usa_feed_como_fallback(self) -> None:
        offers = _run({"offers": [_offer(source_url="javascript:alert(1)")]})
        assert len(offers) == 1
        assert offers[0].source_url == FEED_URL

    def test_dominio_malformado_nao_vira_identidade(self) -> None:
        offers = _run({"offers": [_offer(store_domain="javascript:alert(1)")]})
        assert offers[0].store_domain is None


class TestMaliciousFields:
    @pytest.mark.parametrize("price", [0, -1, "-10", None, "", True, "nao-e-preco"])
    def test_preco_invalido_descarta_oferta(self, price: Any) -> None:
        assert _run({"offers": [_offer(price=price)]}) == []

    def test_currency_invalida_descarta_oferta(self) -> None:
        assert _run({"offers": [_offer(currency="REAL")]}) == []

    def test_titulo_gigante_e_recusado(self) -> None:
        assert _run({"offers": [_offer(title="x" * 501)]}) == []

    def test_caracteres_de_controle_sao_removidos(self) -> None:
        offers = _run({"offers": [_offer(title="Redmi\x1b[31m Note\x00 14\u202e 256GB")]})
        assert len(offers) == 1
        assert "\x1b" not in offers[0].title
        assert "\x00" not in offers[0].title
        assert "\u202e" not in offers[0].title

    def test_quebra_de_linha_nao_forja_linhas_no_terminal(self) -> None:
        offers = _run(
            {
                "offers": [
                    _offer(
                        title="Redmi Note 14\n[bold red]OFERTA FALSA[/bold red]\r\n256GB",
                        store="Loja Exemplo\n>> clique aqui",
                    )
                ]
            }
        )
        assert len(offers) == 1
        assert "\n" not in offers[0].title
        assert "\r" not in offers[0].title
        assert "\n" not in offers[0].store_name
        assert offers[0].title == "Redmi Note 14 [bold red]OFERTA FALSA[/bold red] 256GB"

    def test_specs_sao_limitadas(self) -> None:
        specs = {f"campo{index}": "x" * 201 for index in range(100)}
        offers = _run({"offers": [_offer(specs=specs)]})
        assert offers[0].specs == {}

    def test_specs_validas_sao_preservadas(self) -> None:
        offers = _run({"offers": [_offer(specs={"memoria_ram": "8GB"})]})
        assert offers[0].specs == {"memoria_ram": "8GB"}

    def test_list_price_negativo_e_descartado(self) -> None:
        offers = _run({"offers": [_offer(list_price="-10")]})
        assert offers[0].list_price_cents is None

    def test_shipping_negativo_e_descartado(self) -> None:
        offers = _run({"offers": [_offer(shipping="-10")]})
        assert offers[0].shipping_cents is None


class TestMaliciousCoupons:
    def test_codigo_gigante_e_ignorado(self) -> None:
        offers = _run(
            {"offers": [_offer(coupons=[{"code": "X" * 101, "kind": "percent", "value": 10}])]}
        )
        assert offers[0].coupons == ()

    def test_percentual_acima_de_100_e_ignorado(self) -> None:
        offers = _run(
            {"offers": [_offer(coupons=[{"code": "X", "kind": "percent", "value": 500}])]}
        )
        assert offers[0].coupons == ()

    def test_cupom_com_url_maliciosa_nao_e_criado(self) -> None:
        offers = _run(
            {
                "offers": [
                    _offer(
                        coupons=[
                            {
                                "code": "X",
                                "kind": "fixed",
                                "value": 10,
                                "url": "javascript:alert(1)",
                            }
                        ]
                    )
                ]
            }
        )
        assert offers[0].coupons[0].code == "X"


class TestMalformedFeed:
    def test_json_invalido_vira_http_error(self) -> None:
        async def go() -> None:
            def handler(_request: httpx.Request) -> httpx.Response:
                return httpx.Response(200, text="<html>erro</html>")

            client = HttpClient(
                user_agent="test",
                transport=httpx.MockTransport(handler),
                retry_delay=0,
                guard_urls=False,
            )
            try:
                await FeedAdapter(client, [FEED_URL]).search(QuerySpec(product="x"))
            finally:
                await client.aclose()

        with pytest.raises(HttpError, match="JSON"):
            asyncio.run(go())

    @pytest.mark.parametrize("payload", [{}, {"offers": {}}, {"offers": "x"}, []])
    def test_payload_sem_lista_offers_falha(self, payload: Any) -> None:
        with pytest.raises(ValueError, match="offers"):
            _run(payload)

    def test_itens_que_nao_sao_objetos_sao_ignorados(self) -> None:
        assert _run({"offers": [None, 1, "x", [], _offer()]})

    def test_limite_de_ofertas_por_feed(self) -> None:
        payload = {"offers": [_offer(url=f"https://loja.example/{index}") for index in range(600)]}
        offers = _run(payload)
        assert len(offers) == 500


class TestMaliciousPromotionAndReviews:
    def test_label_de_promocao_gigante_ignora_promocao(self) -> None:
        offers = _run(
            {
                "offers": [
                    _offer(
                        promotion={
                            "kind": "flash",
                            "label": "x" * 201,
                            "ends_at": "2026-03-16T12:00:00Z",
                        }
                    )
                ]
            }
        )
        assert offers[0].promotion is None

    def test_avaliacoes_invalidas_sao_ignoradas(self) -> None:
        offers = _run({"offers": [_offer(reviews={"rating": 9, "count": 100})]})
        assert offers[0].reviews is None

    def test_avaliacoes_com_distribuicao_invalida_nao_quebram(self) -> None:
        offers = _run(
            {
                "offers": [
                    _offer(
                        reviews={
                            "rating": 4.5,
                            "count": 10,
                            "distribution": {"5": "muitas", "9": 10, "1": -1},
                        }
                    )
                ]
            }
        )
        assert offers[0].reviews is not None
        assert offers[0].reviews.distribution == {}
