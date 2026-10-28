"""Integração com servidor HTTP local (sem rede externa)."""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from dealhunter.adapters.http.client import BlockedUrlError, HttpClient, HttpError
from dealhunter.adapters.http.robots import RobotsGuard
from dealhunter.adapters.sources.feed import FeedAdapter
from dealhunter.application.dto import QuerySpec
from dealhunter.domain.models import CollectedOffer


class _Handler(BaseHTTPRequestHandler):
    robots = "User-agent: *\nAllow: /\n"
    offers: dict[str, object] = {
        "offers": [
            {
                "title": "Xiaomi Redmi Note 14 256GB",
                "url": "https://loja.example/produto/1",
                "price": "1649.90",
                "store": "Loja Exemplo",
                "store_domain": "loja.example",
            }
        ]
    }
    broken_json = False
    requests: list[str] = []

    def do_GET(self) -> None:  # noqa: N802 - API do stdlib
        _Handler.requests.append(self.path)
        if self.path == "/robots.txt":
            if self.robots == "404":
                self._send(404, "não encontrado", "text/plain")
            else:
                self._send(200, self.robots, "text/plain")
        elif self.path == "/offers.json":
            if self.broken_json:
                self._send(200, "<html>erro</html>", "text/html")
            else:
                self._send(200, json.dumps(self.offers), "application/json")
        else:
            self._send(404, "não encontrado", "text/plain")

    def _send(self, status: int, body: str, content_type: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *_args: object) -> None:
        return None


@contextmanager
def _server() -> Iterator[str]:
    _Handler.requests = []
    _Handler.robots = "User-agent: *\nAllow: /\n"
    _Handler.offers = {
        "offers": [
            {
                "title": "Xiaomi Redmi Note 14 256GB",
                "url": "https://loja.example/produto/1",
                "price": "1649.90",
                "store": "Loja Exemplo",
                "store_domain": "loja.example",
            }
        ]
    }
    _Handler.broken_json = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


async def _search(base: str, *, robots: bool = True) -> list[CollectedOffer]:
    client = HttpClient(user_agent="dealhunter-test", guard_urls=False, timeout=5)
    try:
        guard = RobotsGuard(client, user_agent="dealhunter-test") if robots else None
        adapter = FeedAdapter(client, [f"{base}/offers.json"], robots=guard)
        return await adapter.search(QuerySpec(product="redmi"))
    finally:
        await client.aclose()


class TestLocalFeed:
    def test_feed_local_com_robots_permite(self) -> None:
        with _server() as base:
            offers = asyncio.run(_search(base))
        assert len(offers) == 1
        assert offers[0].price_cents == 164_990
        assert "/robots.txt" in _Handler.requests
        assert "/offers.json" in _Handler.requests

    def test_robots_disallow_impede_feed(self) -> None:
        with _server() as base:
            _Handler.robots = "User-agent: *\nDisallow: /offers.json\n"
            with pytest.raises(PermissionError, match="robots"):
                asyncio.run(_search(base))
        assert "/offers.json" not in _Handler.requests

    def test_robots_404_libera_acesso(self) -> None:
        with _server() as base:
            _Handler.robots = "404"
            offers = asyncio.run(_search(base))
        assert len(offers) == 1

    def test_robots_e_cacheado_entre_buscas(self) -> None:
        with _server() as base:

            async def go() -> None:
                client = HttpClient(user_agent="dealhunter-test", guard_urls=False, timeout=5)
                try:
                    guard = RobotsGuard(client, user_agent="dealhunter-test")
                    adapter = FeedAdapter(client, [f"{base}/offers.json"], robots=guard)
                    await adapter.search(QuerySpec(product="redmi"))
                    await adapter.search(QuerySpec(product="redmi"))
                finally:
                    await client.aclose()

            asyncio.run(go())
        assert _Handler.requests.count("/robots.txt") == 1

    def test_json_invalido_vira_http_error(self) -> None:
        with _server() as base:
            _Handler.broken_json = True
            with pytest.raises(HttpError, match="JSON"):
                asyncio.run(_search(base))

    def test_localhost_e_bloqueado_quando_guard_esta_ativo(self) -> None:
        with _server() as base:

            async def go() -> None:
                client = HttpClient(user_agent="test", guard_urls=True, timeout=5)
                try:
                    await client.get_json(f"{base}/offers.json")
                finally:
                    await client.aclose()

            with pytest.raises(BlockedUrlError):
                asyncio.run(go())
        assert _Handler.requests == []
