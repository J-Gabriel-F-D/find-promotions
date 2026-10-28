"""Segurança de notificações: e-mail, canais indisponíveis e abuso."""

from __future__ import annotations

import asyncio
import smtplib

import pytest

from dealhunter.adapters.notify.base import (
    NotificationError,
    NotificationMessage,
    Notifier,
    is_valid_email,
)
from dealhunter.adapters.notify.registry import build_notifier
from dealhunter.adapters.notify.smtp import SmtpChannel
from dealhunter.runtime.config import NotificationSettings


class FakeSMTP:
    instances: list[FakeSMTP] = []
    login_error: Exception | None = None
    send_error: Exception | None = None

    def __init__(self, host: str, port: int, timeout: float = 0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.messages: list[object] = []
        self.credentials: tuple[str, str] | None = None
        FakeSMTP.instances.append(self)

    def __enter__(self) -> FakeSMTP:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def ehlo(self) -> None:
        return None

    def starttls(self) -> None:
        return None

    def login(self, user: str, password: str) -> None:
        if FakeSMTP.login_error:
            raise FakeSMTP.login_error
        self.credentials = (user, password)

    def send_message(self, message: object) -> None:
        if FakeSMTP.send_error:
            raise FakeSMTP.send_error
        self.messages.append(message)


@pytest.fixture(autouse=True)
def reset_fake_smtp():
    FakeSMTP.instances.clear()
    FakeSMTP.login_error = None
    FakeSMTP.send_error = None
    yield


def _channel(**overrides: object) -> SmtpChannel:
    values: dict[str, object] = {
        "host": "smtp.example.com",
        "port": 587,
        "sender": "contato@dealhunter.example",
        "recipient": "joao.silva@example.com",
        "user": "smtp-user",
        "password": "hunter2",
        "use_starttls": True,
    }
    values.update(overrides)
    return SmtpChannel(**values)  # type: ignore[arg-type]


class TestEmailValidation:
    @pytest.mark.parametrize(
        "address",
        [
            "joao.silva@example.com",
            "a+b@sub.example.com",
        ],
    )
    def test_aceita_enderecos_validos(self, address: str) -> None:
        assert is_valid_email(address)

    @pytest.mark.parametrize(
        "address",
        [
            "",
            "sem-arroba",
            "a@b",
            "a b@example.com",
            "a@example.com\r\nBcc: evil@example.com",
            "a@example.com\nBcc: evil@example.com",
            "<script>@example.com",
            "a@example.com, b@example.com",
        ],
    )
    def test_recusa_enderecos_invalidos_ou_com_injecao(self, address: str) -> None:
        assert not is_valid_email(address)

    def test_assunto_com_quebra_de_linha_e_recusado(self) -> None:
        with pytest.raises(ValueError, match="quebras de linha"):
            NotificationMessage("Oi\r\nBcc: evil@example.com", "corpo")

    def test_assunto_longo_demais_e_recusado(self) -> None:
        with pytest.raises(ValueError, match="muito longo"):
            NotificationMessage("x" * 201, "corpo")

    def test_corpo_longo_demais_e_recusado(self) -> None:
        with pytest.raises(ValueError, match="muito longo"):
            NotificationMessage("assunto", "x" * 50_001)


class TestSmtp:
    def test_envia_email_valido(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
        channel = _channel()
        channel.send(NotificationMessage("Oferta", "Preço caiu"))

        smtp = FakeSMTP.instances[0]
        assert smtp.host == "smtp.example.com"
        assert smtp.credentials == ("smtp-user", "hunter2")
        assert len(smtp.messages) == 1

    def test_destinatario_com_crlf_nao_chega_ao_smtp(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
        channel = _channel()

        with pytest.raises(NotificationError, match="inválido"):
            channel.send(
                NotificationMessage(
                    "Oferta",
                    "corpo",
                    destination="joao@example.com\r\nBcc: evil@example.com",
                )
            )
        assert FakeSMTP.instances == []

    def test_destinatario_invalido_nao_chega_ao_smtp(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
        channel = _channel(recipient="sem-arroba")

        with pytest.raises(NotificationError, match="inválido"):
            channel.send(NotificationMessage("Oferta", "corpo"))
        assert FakeSMTP.instances == []

    def test_remetente_invalido_nao_chega_ao_smtp(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
        channel = _channel(sender="remetente-invalido")

        with pytest.raises(NotificationError, match="remetente"):
            channel.send(NotificationMessage("Oferta", "corpo"))
        assert FakeSMTP.instances == []

    def test_timeout_vira_erro_generico(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def timeout(*_args: object, **_kwargs: object):
            raise TimeoutError("tempo esgotado")

        monkeypatch.setattr(smtplib, "SMTP", timeout)
        with pytest.raises(NotificationError, match="falha ao enviar e-mail"):
            _channel().send(NotificationMessage("Oferta", "corpo"))

    def test_falha_de_autenticacao_nao_vaza_senha(self, monkeypatch: pytest.MonkeyPatch) -> None:
        FakeSMTP.login_error = smtplib.SMTPAuthenticationError(535, b"credenciais invalidas")
        monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

        with pytest.raises(NotificationError) as exc_info:
            _channel().send(NotificationMessage("Oferta", "corpo"))
        assert "hunter2" not in str(exc_info.value)
        assert "joao.silva" not in str(exc_info.value)
        assert "SMTPAuthenticationError" in str(exc_info.value)

    def test_erro_de_envio_nao_vaza_destinatario(self, monkeypatch: pytest.MonkeyPatch) -> None:
        FakeSMTP.send_error = smtplib.SMTPRecipientsRefused(
            {"joao.silva@example.com": (550, b"desconhecido")}
        )
        monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

        with pytest.raises(NotificationError) as exc_info:
            _channel().send(NotificationMessage("Oferta", "corpo"))
        assert "joao.silva@example.com" not in str(exc_info.value)


class TestNotifierRegistry:
    def test_email_nao_e_ativado_sem_configuracao(self) -> None:
        notifier, warnings = build_notifier(
            NotificationSettings(channels=["console", "email"]),
            printer=lambda _text: None,
            environ={},
        )
        assert notifier.supports("console")
        assert not notifier.supports("email")
        assert any("email" in warning for warning in warnings)

    def test_email_com_remetente_invalido_e_ignorado(self) -> None:
        notifier, warnings = build_notifier(
            NotificationSettings(
                channels=["console"],
                smtp_host="smtp.example.com",
                email_from="invalido",
                email_to="joao@example.com",
            ),
            printer=lambda _text: None,
            environ={},
        )
        assert not notifier.supports("email")
        assert any("remetente inválido" in warning for warning in warnings)

    def test_email_com_destinatario_invalido_e_ignorado(self) -> None:
        notifier, warnings = build_notifier(
            NotificationSettings(
                channels=["console"],
                smtp_host="smtp.example.com",
                email_from="contato@example.com",
                email_to="destinatario-invalido",
            ),
            printer=lambda _text: None,
            environ={},
        )
        assert not notifier.supports("email")
        assert any("destinatário inválido" in warning for warning in warnings)

    def test_canal_sms_whatsapp_nao_e_habilitado_por_engano(self) -> None:
        notifier, warnings = build_notifier(
            NotificationSettings(channels=["console", "sms", "whatsapp"]),
            printer=lambda _text: None,
            environ={},
        )
        assert notifier.available == ("console",)
        assert any("sms" in warning for warning in warnings)
        assert any("whatsapp" in warning for warning in warnings)

    def test_erro_de_canal_e_redigido(self) -> None:
        class Boom:
            id = "console"
            label = "Boom"

            def send(self, _message: NotificationMessage) -> None:
                raise RuntimeError(
                    "password=hunter2 token=abc123 email=joao@example.com telefone 11999999999"
                )

        notifier = Notifier({"console": Boom()})
        ok, error = asyncio.run(notifier.send("console", NotificationMessage("x", "y")))
        assert ok is False
        assert error is not None
        for value in ("hunter2", "abc123", "joao@example.com", "11999999999"):
            assert value not in error
        assert "RuntimeError" in error

    def test_canal_desconhecido_falha_sem_executar(self) -> None:
        notifier = Notifier({})
        ok, error = asyncio.run(notifier.send("../../bin/sh", NotificationMessage("x", "y")))
        assert ok is False
        assert error is not None
        assert "não configurado" in error
