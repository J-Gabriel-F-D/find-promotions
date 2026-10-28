"""Limites de requisições e de abuso da API interna."""

from __future__ import annotations

import asyncio
import time

import httpx

from dealhunter.adapters.http.client import HttpClient


def test_sem_limite_nao_configura_intervalo() -> None:
    async def go() -> None:
        client = HttpClient(user_agent="test", requests_per_minute=None)
        try:
            assert client._min_interval == 0.0
        finally:
            await client.aclose()

    asyncio.run(go())


def test_limite_espaca_requisicoes() -> None:
    async def go() -> None:
        # 1200 req/min => 50 ms entre chamadas.
        client = HttpClient(user_agent="test", requests_per_minute=1200)
        try:
            started = time.monotonic()
            await client._throttle()
            await client._throttle()
            elapsed = time.monotonic() - started
        finally:
            await client.aclose()
        assert elapsed >= 0.04

    asyncio.run(go())


def test_requisicoes_concorrentes_respeitam_o_lock() -> None:
    async def go() -> None:
        client = HttpClient(user_agent="test", requests_per_minute=1200)
        try:
            started = time.monotonic()
            await asyncio.gather(client._throttle(), client._throttle())
            elapsed = time.monotonic() - started
        finally:
            await client.aclose()
        assert elapsed >= 0.04

    asyncio.run(go())


def test_rate_limit_nao_impede_resposta_normal() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    async def go() -> object:
        client = HttpClient(
            user_agent="test",
            transport=httpx.MockTransport(handler),
            guard_urls=False,
            requests_per_minute=600,
        )
        try:
            return await client.get_json("https://public.example/x")
        finally:
            await client.aclose()

    assert asyncio.run(go()) == {"ok": True}
