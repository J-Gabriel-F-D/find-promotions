"""Canal SMS por API HTTP oficial configurável.

O DealHunter não usa gateways não documentados nem envia SMS por modem. O
usuário configura o endpoint HTTPS do provedor oficial; o adapter envia um JSON
mínimo ``{"to", "from", "message"}`` com token Bearer. Redirecionamentos são
recusados e o endpoint não pode apontar para hosts locais/privados.
"""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

import httpx

from dealhunter.adapters.notify.base import (
    NotificationError,
    NotificationMessage,
    normalize_phone,
)

MAX_SMS_CHARS = 1_600
_SENDER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,31}$")


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

    return f"https://{parts.netloc}{parts.path or '/'}"


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
        self._to = normalized
        self._from = normalized_sender
        self._token = token
        self._timeout = timeout
        self._transport = transport

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
        }
        try:
            with httpx.Client(
                timeout=self._timeout,
                follow_redirects=False,
                transport=self._transport,
            ) as client:
                response = client.post(self._endpoint, json=payload, headers=headers)
        except (httpx.HTTPError, OSError) as exc:
            raise NotificationError(f"falha ao enviar SMS ({type(exc).__name__})") from exc

        if not 200 <= response.status_code < 300:
            raise NotificationError(f"falha ao enviar SMS (HTTP {response.status_code})")
