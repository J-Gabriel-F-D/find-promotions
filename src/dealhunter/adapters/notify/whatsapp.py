"""Canal WhatsApp pela API oficial Meta Cloud API.

Somente API oficial: não há automação de WhatsApp Web, QR code ou sessão não
oficial. O envio exige um **template aprovado** pela Meta; o DealHunter envia o
resumo da oferta como parâmetro ``{{1}}`` do corpo do template.

O token nunca é escrito em logs, mensagens de erro ou no banco. A URL da API é
fixa (``graph.facebook.com``) e redirecionamentos são recusados.
"""

from __future__ import annotations

import re

import httpx

from dealhunter.adapters.notify.base import (
    NotificationError,
    NotificationMessage,
    normalize_phone,
)

GRAPH_BASE_URL = "https://graph.facebook.com"
MAX_TEMPLATE_PARAM = 1_024
_PHONE_NUMBER_ID = re.compile(r"^[0-9]{5,32}$")
_TEMPLATE = re.compile(r"^[a-z0-9_]{1,512}$")
_LANGUAGE = re.compile(r"^[a-z]{2}(?:_[A-Z]{2})?$")
_VERSION = re.compile(r"^v[0-9]{1,3}\.[0-9]{1,3}$")


class WhatsAppChannel:
    id = "whatsapp"
    label = "WhatsApp (Meta Cloud API)"

    def __init__(
        self,
        *,
        phone: str,
        phone_number_id: str,
        template: str,
        token: str,
        language: str = "pt_BR",
        api_version: str = "v20.0",
        timeout: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        normalized = normalize_phone(phone)
        if normalized is None:
            raise ValueError("telefone de WhatsApp inválido")
        if not _PHONE_NUMBER_ID.fullmatch(phone_number_id):
            raise ValueError("phone_number_id de WhatsApp inválido")
        if not _TEMPLATE.fullmatch(template):
            raise ValueError("nome de template de WhatsApp inválido")
        if not _LANGUAGE.fullmatch(language):
            raise ValueError("idioma de template de WhatsApp inválido")
        if not _VERSION.fullmatch(api_version):
            raise ValueError("versão da API de WhatsApp inválida")
        if not token:
            raise ValueError("token de WhatsApp ausente")

        self._phone = normalized
        self._phone_number_id = phone_number_id
        self._template = template
        self._token = token
        self._language = language
        self._api_version = api_version
        self._timeout = timeout
        self._transport = transport

    @property
    def endpoint(self) -> str:
        return f"{GRAPH_BASE_URL}/{self._api_version}/{self._phone_number_id}/messages"

    def _destination(self, message: NotificationMessage) -> str:
        if message.destination:
            normalized = normalize_phone(message.destination)
            if normalized is None:
                raise NotificationError("destinatário de WhatsApp inválido")
            return normalized
        return self._phone

    def send(self, message: NotificationMessage) -> None:
        to = self._destination(message)
        text = f"{message.subject}\n{message.body}"[:MAX_TEMPLATE_PARAM]
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to.lstrip("+"),
            "type": "template",
            "template": {
                "name": self._template,
                "language": {"code": self._language},
                "components": [
                    {
                        "type": "body",
                        "parameters": [{"type": "text", "text": text}],
                    }
                ],
            },
        }
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
                response = client.post(self.endpoint, json=payload, headers=headers)
        except (httpx.HTTPError, OSError) as exc:
            raise NotificationError(f"falha ao enviar WhatsApp ({type(exc).__name__})") from exc

        if not 200 <= response.status_code < 300:
            # Não ecoa corpo/resposta: pode conter telefone ou detalhes do token.
            raise NotificationError(f"falha ao enviar WhatsApp (HTTP {response.status_code})")
