"""Canal de e-mail via SMTP.

A senha **nunca** fica na configuração: vem de variavel de ambiente (ou do
keyring, numa fase seguinte). Sem host configurado, o canal não e registrado.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from dealhunter.adapters.notify.base import NotificationError, NotificationMessage


class SmtpChannel:
    id = "email"
    label = "E-mail"

    def __init__(
        self,
        *,
        host: str,
        port: int,
        sender: str,
        recipient: str | None,
        user: str | None = None,
        password: str | None = None,
        use_starttls: bool = True,
        timeout: float = 20.0,
    ) -> None:
        self._host = host
        self._port = port
        self._sender = sender
        self._default_recipient = recipient
        self._user = user
        self._password = password
        self._starttls = use_starttls
        self._timeout = timeout

    def send(self, message: NotificationMessage) -> None:
        recipient = message.destination or self._default_recipient
        if not recipient:
            raise NotificationError("destinatário de e-mail não configurado")

        email = EmailMessage()
        email["Subject"] = message.subject
        email["From"] = self._sender
        email["To"] = recipient
        email.set_content(message.body)

        try:
            with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as smtp:
                smtp.ehlo()
                if self._starttls:
                    smtp.starttls()
                    smtp.ehlo()
                if self._user and self._password:
                    smtp.login(self._user, self._password)
                smtp.send_message(email)
        except (smtplib.SMTPException, OSError) as exc:
            raise NotificationError(f"falha ao enviar e-mail: {exc}") from exc
