"""Construcao dos canais de notificação a partir da configuração."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping

from dealhunter.adapters.notify.base import Notifier
from dealhunter.adapters.notify.console import ConsoleChannel
from dealhunter.adapters.notify.smtp import SmtpChannel
from dealhunter.runtime.config import NotificationSettings


def build_notifier(
    settings: NotificationSettings,
    *,
    printer: Callable[[str], None],
    environ: Mapping[str, str] | None = None,
) -> tuple[Notifier, list[str]]:
    """Registra apenas canais realmente utilizaveis; devolve avisos do resto."""
    environ = os.environ if environ is None else environ
    channels: dict[str, object] = {"console": ConsoleChannel(printer)}
    warnings: list[str] = []

    if settings.smtp_host and (settings.email_to or settings.email_from):
        sender = settings.email_from or settings.smtp_user
        if not sender:
            warnings.append("canal 'email' ignorado: configure 'email_from'")
        else:
            channels["email"] = SmtpChannel(
                host=settings.smtp_host,
                port=settings.smtp_port,
                sender=sender,
                recipient=settings.email_to,
                user=settings.smtp_user,
                password=environ.get(settings.smtp_password_env) or None,
                use_starttls=settings.use_starttls,
            )

    for requested in settings.channels:
        if requested not in channels:
            warnings.append(
                f"canal '{requested}' solicitado na configuração, mas não esta disponível"
            )

    return Notifier(channels), warnings  # type: ignore[arg-type]
