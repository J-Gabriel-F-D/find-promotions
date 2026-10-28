"""Camada HTTP compartilhada por todos os adapters.

Responsabilidades: timeouts, retentativas com backoff + jitter, `Retry-After`,
User-Agent identificável e **proteção contra SSRF**. Nenhum adapter deve usar
``httpx`` diretamente.
"""

from __future__ import annotations

import asyncio
import ipaddress
import random
import re
import socket
import time
from collections.abc import Callable
from contextlib import suppress
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

Resolver = Callable[[str], list[tuple[Any, ...]]]

_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_MAX_REDIRECTS = 5
_SENSITIVE_HEADERS = {"authorization", "cookie", "proxy-authorization"}


def _origin(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    return parts.scheme.lower(), (parts.netloc or "").lower()


def _safe_url(url: str) -> str:
    """URL para logs/erros: sem credenciais, query ou fragmento."""
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return "(url invalida)"
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


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


def _ambiguous_numeric_host(host: str) -> bool:
    """Formas legadas de IP (127.1, 2130706433, 0x7f000001) não passam."""
    if re.fullmatch(r"0x[0-9a-f]+", host, re.IGNORECASE):
        return True
    if re.fullmatch(r"[0-9.]+", host):
        try:
            ipaddress.IPv4Address(host)
        except ValueError:
            return True
    return False


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
    host = host.rstrip(".")

    try:
        ipaddress.ip_address(host)
        literal_ip = True
    except ValueError:
        literal_ip = False

    if literal_ip:
        if not _ip_is_public(host):
            raise BlockedUrlError(f"destino interno bloqueado: {host}", url=url)
        return

    if _ambiguous_numeric_host(host):
        raise BlockedUrlError(f"endereço IP não canônico bloqueado: {host}", url=url)

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
        requests_per_minute: int | None = None,
    ) -> None:
        self._user_agent = user_agent
        self._timeout = timeout
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._resolver = resolver
        self._guard = guard_urls
        self._min_interval = 60.0 / requests_per_minute if requests_per_minute else 0.0
        self._rate_lock = asyncio.Lock()
        self._last_request_at = 0.0
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            # Redirecionamentos são seguidos manualmente para validar cada salto
            # contra SSRF (um 302 para 127.0.0.1 não pode ser acessado).
            follow_redirects=False,
            max_redirects=0,
            transport=transport,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
        )

    async def __aenter__(self) -> HttpClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _throttle(self) -> None:
        """Espaça requisições conforme ``requests_per_minute``.

        O lock serializa o cálculo do próximo horário; sem ele, buscas
        concorrentes poderiam disparar todas ao mesmo tempo.
        """
        if self._min_interval <= 0:
            return
        async with self._rate_lock:
            now = time.monotonic()
            wait = self._last_request_at + self._min_interval - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request_at = time.monotonic()

    async def _get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """GET com redirecionamentos validados salto a salto."""
        current_url = url
        current_params = params
        current_headers = dict(headers) if headers else None
        initial_origin = _origin(url)
        redirects = 0
        while True:
            if self._guard:
                assert_public_url(current_url, resolver=self._resolver)
            await self._throttle()
            response = await self._client.get(
                current_url, params=current_params, headers=current_headers
            )
            current_params = None
            if response.status_code not in _REDIRECT_STATUSES:
                return response

            location = response.headers.get("Location")
            if not location:
                return response
            redirects += 1
            if redirects > _MAX_REDIRECTS:
                raise HttpError(f"muitos redirecionamentos em {_safe_url(url)}", url=_safe_url(url))
            next_url = urljoin(current_url, location)
            if _origin(next_url) != initial_origin and current_headers:
                # Não encaminhar credenciais para outro host/esquema.
                current_headers = {
                    key: value
                    for key, value in current_headers.items()
                    if key.lower() not in _SENSITIVE_HEADERS
                }
            current_url = next_url

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
                response = await self._get(url, params=params, headers=headers)
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < self._max_retries:
                    await self._sleep(attempt)
                    continue
                raise HttpError(
                    f"falha de rede em {_safe_url(url)}: {type(exc).__name__}",
                    url=_safe_url(url),
                ) from exc

            if response.status_code in {408, 425, 429} or response.status_code >= 500:
                last_error = HttpError(
                    f"HTTP {response.status_code} em {_safe_url(url)}",
                    status=response.status_code,
                    url=_safe_url(url),
                )
                if attempt < self._max_retries:
                    await self._sleep(attempt, response.headers.get("Retry-After"))
                    continue
                raise last_error

            if response.status_code >= 400:
                raise HttpError(
                    f"HTTP {response.status_code} em {_safe_url(url)}",
                    status=response.status_code,
                    url=_safe_url(url),
                )

            try:
                return response.json()
            except ValueError as exc:
                raise HttpError(
                    f"resposta não e JSON valido em {_safe_url(url)}", url=_safe_url(url)
                ) from exc

        raise HttpError(
            f"falha apos {self._max_retries + 1} tentativas: {last_error}",
            url=_safe_url(url),
        )

    async def _sleep(self, attempt: int, retry_after: str | None = None) -> None:
        delay = self._retry_delay * (2**attempt)
        if retry_after:
            with suppress(ValueError):
                delay = max(delay, float(retry_after))
        # Jitter evita sincronização; não é usado para segurança criptográfica.
        delay += random.uniform(0, delay * 0.1)  # nosec B311
        if delay > 0:
            await asyncio.sleep(delay)

    async def get_text(self, url: str, *, allow_not_found: bool = False) -> str | None:
        """Busca texto simples (ex.: robots.txt), sem retentativas agressivas."""
        if self._guard:
            assert_public_url(url, resolver=self._resolver)
        try:
            response = await self._get(url)
        except httpx.HTTPError as exc:
            raise HttpError(
                f"falha de rede em {_safe_url(url)}: {type(exc).__name__}",
                url=_safe_url(url),
            ) from exc

        if response.status_code == 404 and allow_not_found:
            return None
        if response.status_code >= 400:
            raise HttpError(
                f"HTTP {response.status_code} em {_safe_url(url)}",
                status=response.status_code,
                url=_safe_url(url),
            )
        return response.text
