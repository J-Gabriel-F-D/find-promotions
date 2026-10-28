"""Camada HTTP compartilhada por todos os adapters.

Responsabilidades: timeouts, retentativas com backoff + jitter, `Retry-After`,
User-Agent identificável e **proteção contra SSRF**. Nenhum adapter deve usar
``httpx`` diretamente.
"""

from __future__ import annotations

import asyncio
import ipaddress
import random
import socket
from collections.abc import Callable
from contextlib import suppress
from typing import Any
from urllib.parse import urlsplit

import httpx

Resolver = Callable[[str], list[tuple[Any, ...]]]


class HttpError(RuntimeError):
    """Falha de rede ou resposta HTTP invalida."""

    def __init__(self, message: str, *, status: int | None = None, url: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.url = url


class BlockedUrlError(HttpError):
    """URL recusada pela politica de segurança (ex.: IP privado)."""


def _ip_is_public(raw_ip: str) -> bool:
    try:
        address = ipaddress.ip_address(raw_ip)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def assert_public_url(url: str, *, resolver: Resolver | None = None) -> None:
    """Recusa esquemas não-HTTP, credenciais embutidas e destinos internos.

    A checagem de DNS e feita **antes** da requisicao e cobre todos os IPs
    resolvidos (defesa classica contra SSRF / DNS rebinding simples).
    """
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"}:
        raise BlockedUrlError(f"esquema não permitido: {parts.scheme or '(vazio)'}", url=url)
    if parts.username or parts.password:
        raise BlockedUrlError("URL não pode conter credenciais embutidas", url=url)

    host = parts.hostname
    if not host:
        raise BlockedUrlError("URL sem host", url=url)

    try:
        ipaddress.ip_address(host)
        literal_ip = True
    except ValueError:
        literal_ip = False

    if literal_ip:
        if not _ip_is_public(host):
            raise BlockedUrlError(f"destino interno bloqueado: {host}", url=url)
        return

    if host.lower() in {"localhost", "localhost.localdomain"} or host.lower().endswith(".local"):
        raise BlockedUrlError(f"destino interno bloqueado: {host}", url=url)

    resolve = resolver or (lambda name: socket.getaddrinfo(name, None))
    try:
        infos = resolve(host)
    except OSError as exc:
        raise HttpError(f"não foi possível resolver {host}: {exc}", url=url) from exc

    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        address = str(sockaddr[0])
        if not _ip_is_public(address):
            raise BlockedUrlError(f"{host} resolve para IP interno ({address})", url=url)


class HttpClient:
    """Cliente assincrono com retentativa e limites conservadores."""

    def __init__(
        self,
        *,
        user_agent: str,
        timeout: float = 20.0,
        max_retries: int = 2,
        retry_delay: float = 0.5,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: Resolver | None = None,
        guard_urls: bool = True,
    ) -> None:
        self._user_agent = user_agent
        self._timeout = timeout
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._resolver = resolver
        self._guard = guard_urls
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
            max_redirects=5,
            transport=transport,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
        )

    async def __aenter__(self) -> HttpClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        if self._guard:
            assert_public_url(url, resolver=self._resolver)

        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.get(url, params=params, headers=headers)
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < self._max_retries:
                    await self._sleep(attempt)
                    continue
                raise HttpError(f"falha de rede em {url}: {exc}", url=url) from exc

            if response.status_code in {408, 425, 429} or response.status_code >= 500:
                last_error = HttpError(
                    f"HTTP {response.status_code} em {url}",
                    status=response.status_code,
                    url=url,
                )
                if attempt < self._max_retries:
                    await self._sleep(attempt, response.headers.get("Retry-After"))
                    continue
                raise last_error

            if response.status_code >= 400:
                raise HttpError(
                    f"HTTP {response.status_code} em {url}",
                    status=response.status_code,
                    url=url,
                )

            try:
                return response.json()
            except ValueError as exc:
                raise HttpError(f"resposta não e JSON valido em {url}", url=url) from exc

        raise HttpError(f"falha apos {self._max_retries + 1} tentativas: {last_error}", url=url)

    async def _sleep(self, attempt: int, retry_after: str | None = None) -> None:
        delay = self._retry_delay * (2**attempt)
        if retry_after:
            with suppress(ValueError):
                delay = max(delay, float(retry_after))
        delay += random.uniform(0, delay * 0.1)
        if delay > 0:
            await asyncio.sleep(delay)

    async def get_text(self, url: str, *, allow_not_found: bool = False) -> str | None:
        """Busca texto simples (ex.: robots.txt), sem retentativas agressivas."""
        if self._guard:
            assert_public_url(url, resolver=self._resolver)
        try:
            response = await self._client.get(url)
        except httpx.HTTPError as exc:
            raise HttpError(f"falha de rede em {url}: {exc}", url=url) from exc

        if response.status_code == 404 and allow_not_found:
            return None
        if response.status_code >= 400:
            raise HttpError(
                f"HTTP {response.status_code} em {url}", status=response.status_code, url=url
            )
        return response.text
