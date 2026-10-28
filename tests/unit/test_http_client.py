"""Testes de seguranca e resiliência do cliente HTTP."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from dealhunter.adapters.http.client import (
    BlockedUrlError,
    HttpClient,
    HttpError,
    assert_public_url,
)

PUBLIC_RESOLVER = lambda _host: [(2, 1, 6, "", ("93.184.216.34", 0))]  # noqa: E731


class TestSsrfGuard:
    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/admin",
            "http://localhost:8080/",
            "http://10.0.0.1/",
            "http://172.16.5.4/",
            "http://192.168.0.1/",
            "http://169.254.169.254/latest/meta-data/",
            "http://[::1]/",
            "http://0.0.0.0/",
        ],
    )
    def test_bloqueia_destinos_internos(self, url: str) -> None:
        with pytest.raises(BlockedUrlError):
            assert_public_url(url, resolver=PUBLIC_RESOLVER)

    def test_bloqueia_esquema_nao_http(self) -> None:
        with pytest.raises(BlockedUrlError):
            assert_public_url("file:///etc/passwd")

    def test_bloqueia_credenciais_embutidas(self) -> None:
        with pytest.raises(BlockedUrlError):
            assert_public_url("https://user:pass@exemplo.com/")

    def test_bloqueia_host_que_resolve_para_ip_privado(self) -> None:
        def resolver(_host: str) -> list[tuple]:
            return [(2, 1, 6, "", ("192.168.1.10", 0))]

        with pytest.raises(BlockedUrlError):
            assert_public_url("https://interno.exemplo.com/", resolver=resolver)

    def test_aceita_https_publico(self) -> None:
        assert_public_url("https://api.mercadolibre.com/sites/MLB/search", resolver=PUBLIC_RESOLVER)


class TestHttpClient:
    def test_retenta_em_429_e_depois_sucede(self) -> None:
        calls = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["count"] += 1
            if calls["count"] == 1:
                return httpx.Response(429, headers={"Retry-After": "0"})
            return httpx.Response(200, json={"ok": True})

        async def run() -> object:
            client = HttpClient(
                user_agent="test",
                transport=httpx.MockTransport(handler),
                retry_delay=0,
                guard_urls=False,
            )
            try:
                return await client.get_json("https://api.example.com/x")
            finally:
                await client.aclose()

        assert asyncio.run(run()) == {"ok": True}
        assert calls["count"] == 2

    def test_desiste_apos_tentativas(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        async def run() -> None:
            client = HttpClient(
                user_agent="test",
                max_retries=1,
                transport=httpx.MockTransport(handler),
                retry_delay=0,
                guard_urls=False,
            )
            try:
                await client.get_json("https://api.example.com/x")
            finally:
                await client.aclose()

        with pytest.raises(HttpError):
            asyncio.run(run())

    def test_erro_4xx_nao_retenta(self) -> None:
        calls = {"count": 0}

        def handler(_request: httpx.Request) -> httpx.Response:
            calls["count"] += 1
            return httpx.Response(404)

        async def run() -> None:
            client = HttpClient(
                user_agent="test",
                transport=httpx.MockTransport(handler),
                retry_delay=0,
                guard_urls=False,
            )
            try:
                await client.get_json("https://api.example.com/x")
            finally:
                await client.aclose()

        with pytest.raises(HttpError):
            asyncio.run(run())
        assert calls["count"] == 1

    def test_json_invalido_vira_http_error(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>nao e json</html>")

        async def run() -> None:
            client = HttpClient(
                user_agent="test",
                transport=httpx.MockTransport(handler),
                retry_delay=0,
                guard_urls=False,
            )
            try:
                await client.get_json("https://api.example.com/x")
            finally:
                await client.aclose()

        with pytest.raises(HttpError):
            asyncio.run(run())

    def test_get_text_trata_404_quando_permitido(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        async def run() -> str | None:
            client = HttpClient(
                user_agent="test",
                transport=httpx.MockTransport(handler),
                retry_delay=0,
                guard_urls=False,
            )
            try:
                return await client.get_text("https://example.com/robots.txt", allow_not_found=True)
            finally:
                await client.aclose()

        assert asyncio.run(run()) is None
