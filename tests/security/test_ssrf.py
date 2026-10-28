"""Proteção SSRF no cliente HTTP, incluindo cada salto de redirecionamento."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from dealhunter.adapters.http.client import (
    BlockedUrlError,
    HttpClient,
    HttpError,
    assert_public_url,
)

PUBLIC_IP = "93.184.216.34"
PRIVATE_IP = "192.168.1.55"


def _resolver(host: str) -> list[tuple[Any, ...]]:
    if host.rstrip(".").lower() in {"interno.example", "localhost"}:
        return [(2, 1, 6, "", (PRIVATE_IP, 0))]
    return [(2, 1, 6, "", (PUBLIC_IP, 0))]


def _run(
    handler,
    *,
    url: str,
    guard: bool = True,
    retries: int = 0,
) -> Any:
    async def go() -> Any:
        client = HttpClient(
            user_agent="test",
            transport=httpx.MockTransport(handler),
            retry_delay=0,
            max_retries=retries,
            resolver=_resolver,
            guard_urls=guard,
        )
        try:
            return await client.get_json(url)
        finally:
            await client.aclose()

    return asyncio.run(go())


class TestRedirectSsrf:
    def test_redirecionamento_para_localhost_e_bloqueado(self) -> None:
        calls = {"n": 0}

        def handler(_request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(302, headers={"Location": "http://127.0.0.1/admin"})

        with pytest.raises(BlockedUrlError):
            _run(handler, url="https://public.example/ofertas")
        assert calls["n"] == 1

    def test_redirecionamento_para_host_privado_e_bloqueado(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"Location": "http://interno.example/x"})

        with pytest.raises(BlockedUrlError):
            _run(handler, url="https://public.example/ofertas")

    def test_redirecionamento_para_metadata_cloud_e_bloqueado(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                301, headers={"Location": "http://169.254.169.254/latest/meta-data"}
            )

        with pytest.raises(BlockedUrlError):
            _run(handler, url="https://public.example/ofertas")

    def test_redirecionamento_para_file_scheme_e_bloqueado(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"Location": "file:///etc/passwd"})

        with pytest.raises(BlockedUrlError):
            _run(handler, url="https://public.example/ofertas")

    def test_redirecionamento_relativo_para_destino_interno_e_bloqueado(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"Location": "//127.0.0.1/segredo"})

        with pytest.raises(BlockedUrlError):
            _run(handler, url="https://public.example/ofertas")

    def test_redirecionamento_com_credenciais_e_bloqueado(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"Location": "https://user:pass@public.example/x"})

        with pytest.raises(BlockedUrlError):
            _run(handler, url="https://public.example/ofertas")

    def test_redirecionamento_publico_e_seguido(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/ofertas":
                return httpx.Response(302, headers={"Location": "/v2/ofertas"})
            return httpx.Response(200, json={"ok": True})

        assert _run(handler, url="https://public.example/ofertas") == {"ok": True}

    def test_excesso_de_redirecionamentos_falha(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"Location": "https://public.example/loop"})

        with pytest.raises(HttpError, match="redirecionamentos"):
            _run(handler, url="https://public.example/ofertas")

    def test_redirecionamento_em_get_text_tambem_e_validado(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"Location": "http://10.0.0.1/robots.txt"})

        async def go() -> None:
            client = HttpClient(
                user_agent="test",
                transport=httpx.MockTransport(handler),
                resolver=_resolver,
                guard_urls=True,
            )
            try:
                await client.get_text("https://public.example/robots.txt")
            finally:
                await client.aclose()

        with pytest.raises(BlockedUrlError):
            asyncio.run(go())


class TestUrlValidation:
    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost./",
            "http://[::ffff:127.0.0.1]/",
            "http://0x7f000001/",
            "https:///sem-host",
        ],
    )
    def test_destinos_ambiguos_sao_recusados(self, url: str) -> None:
        with pytest.raises((BlockedUrlError, HttpError)):
            assert_public_url(url, resolver=_resolver)

    def test_falha_de_dns_nao_vira_requisicao(self) -> None:
        def resolver(_host: str) -> list[tuple[Any, ...]]:
            raise OSError("dns offline")

        with pytest.raises(HttpError, match="resolver"):
            assert_public_url("https://quebrado.example/", resolver=resolver)

    def test_url_com_token_nao_vaza_na_mensagem_de_erro(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        with pytest.raises(HttpError) as exc_info:
            _run(
                handler,
                url="https://public.example/ofertas?access_token=segredo-123",
                retries=0,
            )
        assert "segredo-123" not in str(exc_info.value)
