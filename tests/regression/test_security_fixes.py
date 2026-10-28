"""Regressões de falhas de segurança encontradas e corrigidas nesta fase."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx
import pytest

from dealhunter.adapters.http.client import BlockedUrlError, HttpClient
from dealhunter.adapters.notify.base import NotificationMessage
from dealhunter.adapters.sources.base import CollectorRunner
from dealhunter.application.dto import QuerySpec
from dealhunter.domain.models import CollectedOffer
from dealhunter.runtime.config import AppConfig, mask_config_pii
from dealhunter.services import matching


def _offer(**overrides: object) -> CollectedOffer:
    values: dict[str, object] = {
        "source_id": "test",
        "title": "Xiaomi Redmi Note 14 256GB",
        "url": "https://loja.example/1",
        "source_url": "https://loja.example/feed",
        "price_cents": 100_000,
        "brand": "Xiaomi",
        "collected_at": datetime(2026, 3, 15, tzinfo=UTC),
    }
    values.update(overrides)
    return CollectedOffer(**values)  # type: ignore[arg-type]


def test_marca_com_caixa_diferente_nao_descarta_oferta_valida() -> None:
    spec = QuerySpec(product="redmi", brand="xiaomi")
    assert matching.evaluate(spec, _offer(brand="Xiaomi")) is None
    assert matching.evaluate(spec, _offer(brand="SAMSUNG")) == "marca_diferente"


def test_redirecionamento_interno_nao_e_seguido() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/segredo"})

    async def go() -> None:
        client = HttpClient(
            user_agent="test",
            transport=httpx.MockTransport(handler),
            guard_urls=True,
            resolver=lambda _host: [(2, 1, 6, "", ("93.184.216.34", 0))],
        )
        try:
            await client.get_json("https://public.example/ofertas")
        finally:
            await client.aclose()

    with pytest.raises(BlockedUrlError):
        asyncio.run(go())
    assert calls["n"] == 1


def test_redirecionamento_cross_origin_nao_encaminha_credenciais() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "api.example":
            return httpx.Response(302, headers={"Location": "https://outro.example/recurso"})
        return httpx.Response(200, json={"ok": True})

    async def go() -> object:
        client = HttpClient(
            user_agent="test",
            transport=httpx.MockTransport(handler),
            guard_urls=False,
            retry_delay=0,
        )
        try:
            return await client.get_json(
                "https://api.example/ofertas",
                headers={"Authorization": "Bearer segredo-123", "X-Trace": "abc"},
            )
        finally:
            await client.aclose()

    assert asyncio.run(go()) == {"ok": True}
    assert len(seen) == 2
    assert seen[0].headers["Authorization"] == "Bearer segredo-123"
    assert "authorization" not in seen[1].headers
    assert seen[1].headers["X-Trace"] == "abc"


def test_assunto_de_email_com_crlf_e_rejeitado() -> None:
    with pytest.raises(ValueError):
        NotificationMessage("Oi\r\nBcc: evil@example.com", "corpo")


def test_config_show_nao_expoe_email_real() -> None:
    config = AppConfig.model_validate({"notifications": {"email_to": "joao.silva@example.com"}})
    assert mask_config_pii(config).notifications.email_to == "j***@example.com"


def test_erro_de_fonte_nao_vaza_token() -> None:
    class Bad:
        id = "bad"
        label = "Ruim"
        capabilities = frozenset({"search"})

        async def search(self, _spec: QuerySpec) -> list[CollectedOffer]:
            raise RuntimeError("token=segredo-123")

    results = asyncio.run(CollectorRunner([Bad()]).run(QuerySpec(product="x")))
    assert results[0].status.status == "error"
    assert results[0].status.error is not None
    assert "segredo-123" not in results[0].status.error
