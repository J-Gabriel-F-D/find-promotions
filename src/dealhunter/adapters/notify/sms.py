"""Canal SMS por API HTTP oficial configurável.

O DealHunter não usa gateways não documentados nem envia SMS por modem. O
usuário configura o endpoint HTTPS do provedor oficial; o adapter envia um JSON
mínimo ``{"to", "from", "message"}`` com token Bearer. Redirecionamentos são
recusados e o endpoint não pode apontar para hosts locais/privados.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from collections.abc import Callable, Sequence
from urllib.parse import urlsplit, urlunsplit

import httpx

from dealhunter.adapters.notify.base import (
    NotificationError,
    NotificationMessage,
    normalize_phone,
)

MAX_SMS_CHARS = 1_600
_SENDER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,31}$")
Resolver = Callable[[str, int], Sequence[str]]


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
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _default_resolver(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos if info[4]]


def resolve_public_addresses(
    host: str,
    port: int,
    *,
    resolver: Resolver | None = None,
) -> tuple[str, ...]:
    """Resolve o host e recusa **todos** os IPs não públicos.

    O IP validado é fixado na conexão (URL com IP + ``Host``/SNI originais),
    portanto uma resposta DNS maliciosa posterior não redireciona o envio para
    a rede interna.
    """
    resolve = resolver or _default_resolver
    try:
        addresses = list(resolve(host, port))
    except OSError as exc:
        raise ValueError("não foi possível resolver o endpoint de SMS") from exc
    if not addresses:
        raise ValueError("endpoint de SMS não resolveu para nenhum endereço")
    validated: list[str] = []
    for raw in addresses:
        if not _ip_is_public(raw):
            raise ValueError("URL de SMS resolve para IP privado")
        if raw not in validated:
            validated.append(raw)
    return tuple(validated)


def _normalize_sender(value: str) -> str | None:
    """Aceita Alphanumeric Sender ID ou um telefone E.164.

    Provedores oficiais permitem remetente alfanumérico curto (ex.: o nome da
    marca). O valor nunca é usado como cabeçalho: vai apenas no corpo JSON.
    """
    stripped = value.strip()
    if _SENDER.fullmatch(stripped):
        return stripped
    return normalize_phone(stripped)


def validate_https_endpoint(url: str) -> str:
    """Valida um endpoint HTTPS público e devolve a URL sem fragmento."""
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        port = parts.port
    except ValueError as exc:
        raise ValueError("URL de SMS inválida") from exc

    if parts.scheme != "https" or not host:
        raise ValueError("URL de SMS deve usar HTTPS")
    if parts.username or parts.password:
        raise ValueError("URL de SMS não pode conter credenciais")
    if parts.fragment:
        raise ValueError("URL de SMS não pode conter fragmento")
    if port is not None and not 1 <= port <= 65_535:
        raise ValueError("porta da URL de SMS inválida")

    lowered = host.lower().rstrip(".")
    if lowered in {"localhost", "localhost.localdomain"} or lowered.endswith(".local"):
        raise ValueError("URL de SMS não pode apontar para host local")

    try:
        address = ipaddress.ip_address(lowered)
    except ValueError:
        address = None
    if address is not None and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        raise ValueError("URL de SMS não pode apontar para IP privado")

    return urlunsplit(("https", parts.netloc, parts.path or "/", parts.query, ""))


class SmsChannel:
    id = "sms"
    label = "SMS (API oficial)"

    def __init__(
        self,
        *,
        endpoint: str,
        to: str,
        token: str,
        sender: str | None = None,
        timeout: float = 20.0,
        transport: httpx.BaseTransport | None = None,
        resolver: Resolver | None = None,
    ) -> None:
        normalized = normalize_phone(to)
        if normalized is None:
            raise ValueError("telefone de SMS inválido")
        normalized_sender = None
        if sender:
            normalized_sender = _normalize_sender(sender)
            if normalized_sender is None:
                raise ValueError("remetente de SMS inválido")
        if not token:
            raise ValueError("token de SMS ausente")

        self._endpoint = validate_https_endpoint(endpoint)
        parts = urlsplit(self._endpoint)
        self._tls_hostname = (parts.hostname or "").rstrip(".")
        self._port = parts.port or 443
        self._host_header = parts.netloc
        self._path = parts.path or "/"
        self._query = parts.query
        self._addresses = resolve_public_addresses(
            self._tls_hostname, self._port, resolver=resolver
        )
        self._to = normalized
        self._from = normalized_sender
        self._token = token
        self._timeout = timeout
        self._transport = transport

    def _pinned_url(self) -> str:
        address = self._addresses[0]
        host = f"[{address}]" if ":" in address else address
        netloc = host if self._port == 443 else f"{host}:{self._port}"
        return urlunsplit(("https", netloc, self._path, self._query, ""))

    def _destination(self, message: NotificationMessage) -> str:
        if message.destination:
            normalized = normalize_phone(message.destination)
            if normalized is None:
                raise NotificationError("destinatário de SMS inválido")
            return normalized
        return self._to

    def send(self, message: NotificationMessage) -> None:
        to = self._destination(message)
        body = message.body[:MAX_SMS_CHARS]
        if not body.strip():
            raise NotificationError("corpo de SMS vazio")

        payload: dict[str, str] = {"to": to, "message": body}
        if self._from:
            payload["from"] = self._from

        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            # A conexão vai para o IP validado; o Host e o SNI continuam sendo
            # o nome original, então a validação do certificado TLS é mantida.
            "Host": self._host_header,
        }
        try:
            # trust_env=False: um proxy ambiente não pode trocar o destino já
            # validado. Quem precisa de proxy corporativo deve configurar um
            # endpoint oficial alcançável diretamente.
            with httpx.Client(
                timeout=self._timeout,
                follow_redirects=False,
                transport=self._transport,
                trust_env=False,
            ) as client:
                response = client.post(
                    self._pinned_url(),
                    json=payload,
                    headers=headers,
                    extensions={"sni_hostname": self._tls_hostname},
                )
        except (httpx.HTTPError, OSError) as exc:
            raise NotificationError(f"falha ao enviar SMS ({type(exc).__name__})") from exc

        if not 200 <= response.status_code < 300:
            raise NotificationError(f"falha ao enviar SMS (HTTP {response.status_code})")
