"""Segurança dos canais WhatsApp e SMS (APIs oficiais simuladas)."""

from __future__ import annotations

import json

import httpx
import pytest

from dealhunter.adapters.notify.base import NotificationError, NotificationMessage, normalize_phone
from dealhunter.adapters.notify.registry import build_notifier
from dealhunter.adapters.notify.sms import SmsChannel, validate_https_endpoint
from dealhunter.adapters.notify.whatsapp import WhatsAppChannel
from dealhunter.runtime.config import NotificationSettings

TOKEN = "tok_super_secreto_123"
PHONE = "+5511999999999"
PUBLIC_IP = "93.184.216.34"


def _public_resolver(_host: str, _port: int) -> list[str]:
    return [PUBLIC_IP]


def _message() -> NotificationMessage:
    return NotificationMessage("Oferta", "Redmi por R$ 1.500")


class TestPhoneValidation:
    @pytest.mark.parametrize(
        "value",
        ["+5511999999999", "5511999999999", "(11) 99999-9999", "00 55 11 99999-9999"],
    )
    def test_aceita_formatos_comuns(self, value: str) -> None:
        normalized = normalize_phone(value)
        assert normalized is not None
        assert normalized.startswith("+")
        assert normalized[1:].isdigit()

    @pytest.mark.parametrize(
        "value",
        ["", "abc", "+551", "123", "+5511999999999999999", "11\n999", "0" * 12, "<script>"],
    )
    def test_recusa_invalidos(self, value: str) -> None:
        assert normalize_phone(value) is None


class TestWhatsApp:
    def _channel(self, transport: httpx.BaseTransport) -> WhatsAppChannel:
        return WhatsAppChannel(
            phone=PHONE,
            phone_number_id="123456789012345",
            template="oferta_dealhunter",
            token=TOKEN,
            language="pt_BR",
            api_version="v20.0",
            transport=transport,
        )

    def test_envia_template_pela_api_oficial(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["auth"] = request.headers.get("authorization")
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200, json={"messages": [{"id": "wamid.1"}]})

        self._channel(httpx.MockTransport(handler)).send(_message())

        assert captured["url"] == ("https://graph.facebook.com/v20.0/123456789012345/messages")
        assert captured["auth"] == f"Bearer {TOKEN}"
        payload = captured["payload"]
        assert isinstance(payload, dict)
        assert payload["messaging_product"] == "whatsapp"
        assert payload["to"] == "5511999999999"
        assert payload["type"] == "template"
        template = payload["template"]
        assert template["name"] == "oferta_dealhunter"
        text = template["components"][0]["parameters"][0]["text"]
        assert "Redmi" in text

    def test_erro_http_nao_vaza_token_nem_telefone(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": {"message": "token inválido"}})

        with pytest.raises(NotificationError) as exc_info:
            self._channel(httpx.MockTransport(handler)).send(_message())
        message = str(exc_info.value)
        assert "HTTP 401" in message
        for secret in (TOKEN, "5511999999999", "token inválido"):
            assert secret not in message

    def test_redirecionamento_nao_e_seguido(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"Location": "https://evil.example"})

        with pytest.raises(NotificationError, match="HTTP 302"):
            self._channel(httpx.MockTransport(handler)).send(_message())

    @pytest.mark.parametrize(
        "overrides",
        [
            {"phone": "invalido"},
            {"phone_number_id": "../x"},
            {"template": "Template Inválido"},
            {"language": "pt-BR"},
            {"api_version": "v20"},
            {"token": ""},
        ],
    )
    def test_configuracao_invalida_falha_cedo(self, overrides: dict[str, str]) -> None:
        values = {
            "phone": PHONE,
            "phone_number_id": "123456789012345",
            "template": "oferta_dealhunter",
            "token": TOKEN,
            "language": "pt_BR",
            "api_version": "v20.0",
        }
        values.update(overrides)
        with pytest.raises(ValueError):
            WhatsAppChannel(**values)  # type: ignore[arg-type]


class TestSms:
    def _channel(self, transport: httpx.BaseTransport, **overrides: object) -> SmsChannel:
        values: dict[str, object] = {
            "endpoint": "https://sms.example.com/v1/messages",
            "to": PHONE,
            "sender": "DealHunter",
            "token": TOKEN,
            "transport": transport,
            "resolver": _public_resolver,
        }
        values.update(overrides)
        return SmsChannel(**values)  # type: ignore[arg-type]

    def test_envia_json_com_bearer(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["host"] = request.headers.get("host")
            captured["sni"] = request.extensions.get("sni_hostname")
            captured["auth"] = request.headers.get("authorization")
            captured["payload"] = json.loads(request.content)
            return httpx.Response(202, json={"ok": True})

        self._channel(httpx.MockTransport(handler)).send(_message())

        # DNS pinning: conecta ao IP validado, mas preserva Host/SNI originais.
        assert captured["url"] == f"https://{PUBLIC_IP}/v1/messages"
        assert captured["host"] == "sms.example.com"
        assert captured["sni"] == "sms.example.com"
        assert captured["auth"] == f"Bearer {TOKEN}"
        payload = captured["payload"]
        assert isinstance(payload, dict)
        assert payload["to"] == PHONE
        assert "Redmi" in payload["message"]

    @pytest.mark.parametrize(
        "resolver",
        [
            lambda _host, _port: ["127.0.0.1"],
            lambda _host, _port: ["10.0.0.5"],
            lambda _host, _port: ["169.254.169.254"],
            lambda _host, _port: [PUBLIC_IP, "192.168.0.10"],
        ],
    )
    def test_dns_para_ip_privado_e_recusado(self, resolver) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(ValueError):
            self._channel(
                httpx.MockTransport(lambda _request: httpx.Response(200)), resolver=resolver
            )

    def test_falha_de_dns_nao_registra_canal(self) -> None:
        def failing(_host: str, _port: int) -> list[str]:
            raise OSError("NXDOMAIN")

        with pytest.raises(ValueError, match="resolver"):
            self._channel(
                httpx.MockTransport(lambda _request: httpx.Response(200)), resolver=failing
            )

    def test_ipv6_validado_e_prefixado_na_url(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["host"] = request.headers.get("host")
            return httpx.Response(202)

        channel = self._channel(
            httpx.MockTransport(handler),
            resolver=lambda _host, _port: ["2606:2800:220:1:248:1893:25c8:1946"],
        )
        channel.send(_message())

        assert str(captured["url"]).startswith("https://[2606:2800:")
        assert captured["host"] == "sms.example.com"

    def test_erro_http_nao_vaza_token(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text=f"falha com {TOKEN}")

        with pytest.raises(NotificationError) as exc_info:
            self._channel(httpx.MockTransport(handler)).send(_message())
        assert "HTTP 500" in str(exc_info.value)
        assert TOKEN not in str(exc_info.value)

    @pytest.mark.parametrize(
        "endpoint",
        [
            "http://sms.example.com/send",
            "https://localhost/send",
            "https://127.0.0.1/send",
            "https://10.0.0.5/send",
            "https://[::1]/send",
            "https://user:pass@sms.example.com/send",
            "https://sms.example.com/send#frag",
        ],
    )
    def test_endpoint_inseguro_e_recusado(self, endpoint: str) -> None:
        with pytest.raises(ValueError):
            validate_https_endpoint(endpoint)

    def test_destinatario_invalido_nao_chega_a_rede(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise AssertionError("não deveria enviar")

        with pytest.raises(NotificationError, match="inválido"):
            self._channel(httpx.MockTransport(handler)).send(
                NotificationMessage("Oferta", "corpo", destination="nao-e-telefone")
            )


class TestRegistry:
    def test_whatsapp_e_sms_so_entram_com_configuracao_completa(self) -> None:
        settings = NotificationSettings(
            channels=["console", "whatsapp", "sms"],
            whatsapp_phone=PHONE,
            whatsapp_phone_number_id="123456789012345",
            whatsapp_template="oferta_dealhunter",
            sms_api_url="https://sms.example.com/v1/messages",
            sms_to=PHONE,
        )
        notifier, warnings = build_notifier(
            settings,
            printer=lambda _text: None,
            environ={
                "DEALHUNTER_WHATSAPP_TOKEN": TOKEN,
                "DEALHUNTER_SMS_TOKEN": TOKEN,
            },
            resolver=_public_resolver,
        )

        assert notifier.supports("whatsapp")
        assert notifier.supports("sms")
        assert warnings == []

    def test_token_ausente_gera_aviso_sem_expor_telefone(self) -> None:
        settings = NotificationSettings(
            channels=["console", "whatsapp"],
            whatsapp_phone=PHONE,
            whatsapp_phone_number_id="123456789012345",
            whatsapp_template="oferta_dealhunter",
        )
        notifier, warnings = build_notifier(settings, printer=lambda _text: None, environ={})

        assert not notifier.supports("whatsapp")
        joined = " ".join(warnings)
        assert "DEALHUNTER_WHATSAPP_TOKEN" in joined
        assert PHONE not in joined

    def test_endpoint_sms_inseguro_nao_registra_canal(self) -> None:
        settings = NotificationSettings(
            channels=["console", "sms"],
            sms_api_url="http://127.0.0.1/send",
            sms_to=PHONE,
        )
        notifier, warnings = build_notifier(
            settings,
            printer=lambda _text: None,
            environ={"DEALHUNTER_SMS_TOKEN": TOKEN},
        )

        assert not notifier.supports("sms")
        assert any("sms" in warning for warning in warnings)
