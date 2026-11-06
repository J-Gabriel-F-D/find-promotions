"""Entrega real a provedores de WhatsApp/SMS. **Opt-in e fora do CI padrão.**

Nenhum teste desta pasta roda sem ``DEALHUNTER_LIVE_NOTIFY=1``. Eles enviam
mensagens reais e podem gerar custo. Configure apenas credenciais oficiais:

WhatsApp Cloud API::

    DEALHUNTER_LIVE_WHATSAPP_PHONE=+5511...
    DEALHUNTER_LIVE_WHATSAPP_PHONE_NUMBER_ID=123456789...
    DEALHUNTER_LIVE_WHATSAPP_TEMPLATE=template_aprovado
    DEALHUNTER_LIVE_WHATSAPP_TOKEN=...
    DEALHUNTER_LIVE_WHATSAPP_LANGUAGE=pt_BR  # opcional

SMS (API oficial HTTPS)::

    DEALHUNTER_LIVE_SMS_ENDPOINT=https://provedor.example/v1/messages
    DEALHUNTER_LIVE_SMS_TOKEN=...
    DEALHUNTER_LIVE_SMS_TO=+5511...
    DEALHUNTER_LIVE_SMS_FROM=DealHunter  # opcional

O corpo é fixo e identificado como teste; nenhum preço ou oferta é inventado.
"""

from __future__ import annotations

import os

import pytest

from dealhunter.adapters.notify.base import NotificationMessage
from dealhunter.adapters.notify.sms import SmsChannel
from dealhunter.adapters.notify.whatsapp import WhatsAppChannel

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("DEALHUNTER_LIVE_NOTIFY") != "1",
        reason="defina DEALHUNTER_LIVE_NOTIFY=1 para enviar mensagens reais",
    ),
]


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.skip(f"defina {name} para o teste live")
    return value


def _message() -> NotificationMessage:
    return NotificationMessage(
        subject="DealHunter (teste)",
        body=(
            "Teste manual do DealHunter. Nenhuma oferta real foi avaliada; "
            "não use esta mensagem como confirmação de preço ou disponibilidade."
        ),
    )


def test_whatsapp_entrega_template_aprovado() -> None:
    channel = WhatsAppChannel(
        phone=_required("DEALHUNTER_LIVE_WHATSAPP_PHONE"),
        phone_number_id=_required("DEALHUNTER_LIVE_WHATSAPP_PHONE_NUMBER_ID"),
        template=_required("DEALHUNTER_LIVE_WHATSAPP_TEMPLATE"),
        token=_required("DEALHUNTER_LIVE_WHATSAPP_TOKEN"),
        language=os.environ.get("DEALHUNTER_LIVE_WHATSAPP_LANGUAGE", "pt_BR"),
    )

    # Sem exceção = provedor aceitou a requisição. A entrega no aparelho ainda
    # depende do provedor e do consentimento do destinatário.
    channel.send(_message())


def test_sms_entrega_pela_api_oficial() -> None:
    channel = SmsChannel(
        endpoint=_required("DEALHUNTER_LIVE_SMS_ENDPOINT"),
        token=_required("DEALHUNTER_LIVE_SMS_TOKEN"),
        to=_required("DEALHUNTER_LIVE_SMS_TO"),
        sender=os.environ.get("DEALHUNTER_LIVE_SMS_FROM") or None,
    )

    channel.send(_message())
