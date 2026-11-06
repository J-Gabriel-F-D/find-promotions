"""Construcao dos canais de notificação a partir da configuração."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping

from dealhunter.adapters.notify.base import Notifier, is_valid_email, normalize_phone
from dealhunter.adapters.notify.console import ConsoleChannel
from dealhunter.adapters.notify.sms import SmsChannel, validate_https_endpoint
from dealhunter.adapters.notify.smtp import SmtpChannel
from dealhunter.adapters.notify.whatsapp import WhatsAppChannel
from dealhunter.runtime.config import NotificationSettings
from dealhunter.runtime.secrets import SecretStore


def build_notifier(
    settings: NotificationSettings,
    *,
    printer: Callable[[str], None],
    environ: Mapping[str, str] | None = None,
    secrets: SecretStore | None = None,
) -> tuple[Notifier, list[str]]:
    """Registra apenas canais realmente utilizaveis; devolve avisos do resto."""
    environ = os.environ if environ is None else environ
    store = secrets or SecretStore(environ=environ)
    channels: dict[str, object] = {"console": ConsoleChannel(printer)}
    warnings: list[str] = []

    if settings.smtp_host and (settings.email_to or settings.email_from):
        sender = settings.email_from or settings.smtp_user
        if not sender:
            warnings.append("canal 'email' ignorado: configure 'email_from'")
        elif not is_valid_email(sender):
            warnings.append("canal 'email' ignorado: remetente inválido")
        elif settings.email_to and not is_valid_email(settings.email_to):
            warnings.append("canal 'email' ignorado: destinatário inválido")
        else:
            channels["email"] = SmtpChannel(
                host=settings.smtp_host,
                port=settings.smtp_port,
                sender=sender,
                recipient=settings.email_to,
                user=settings.smtp_user,
                password=store.get(settings.smtp_password_env),
                use_starttls=settings.use_starttls,
            )

    _build_whatsapp(settings, channels, warnings, store)
    _build_sms(settings, channels, warnings, store)

    for requested in settings.channels:
        if requested not in channels:
            warnings.append(
                f"canal '{requested}' solicitado na configuração, mas não esta disponível"
            )

    return Notifier(channels), warnings  # type: ignore[arg-type]


def _build_whatsapp(
    settings: NotificationSettings,
    channels: dict[str, object],
    warnings: list[str],
    store: SecretStore,
) -> None:
    configured = any(
        (
            settings.whatsapp_phone,
            settings.whatsapp_phone_number_id,
            settings.whatsapp_template,
        )
    )
    if not configured and "whatsapp" not in settings.channels:
        return
    missing = [
        name
        for name, value in (
            ("whatsapp_phone", settings.whatsapp_phone),
            ("whatsapp_phone_number_id", settings.whatsapp_phone_number_id),
            ("whatsapp_template", settings.whatsapp_template),
        )
        if not value
    ]
    token = store.get(settings.whatsapp_token_env)
    if not token:
        missing.append(settings.whatsapp_token_env)
    if missing:
        warnings.append("canal 'whatsapp' ignorado: configure " + ", ".join(missing))
        return
    if token is None:
        return
    if normalize_phone(settings.whatsapp_phone) is None:
        warnings.append("canal 'whatsapp' ignorado: telefone inválido")
        return

    try:
        channels["whatsapp"] = WhatsAppChannel(
            phone=settings.whatsapp_phone or "",
            phone_number_id=settings.whatsapp_phone_number_id or "",
            template=settings.whatsapp_template or "",
            token=token,
            language=settings.whatsapp_template_language,
            api_version=settings.whatsapp_api_version,
        )
    except ValueError as exc:
        warnings.append(f"canal 'whatsapp' ignorado: {exc}")


def _build_sms(
    settings: NotificationSettings,
    channels: dict[str, object],
    warnings: list[str],
    store: SecretStore,
) -> None:
    configured = any((settings.sms_api_url, settings.sms_to))
    if not configured and "sms" not in settings.channels:
        return
    missing = [
        name
        for name, value in (
            ("sms_api_url", settings.sms_api_url),
            ("sms_to", settings.sms_to),
        )
        if not value
    ]
    token = store.get(settings.sms_token_env)
    if not token:
        missing.append(settings.sms_token_env)
    if missing:
        warnings.append("canal 'sms' ignorado: configure " + ", ".join(missing))
        return
    if token is None:
        return

    try:
        endpoint = validate_https_endpoint(settings.sms_api_url or "")
        channels["sms"] = SmsChannel(
            endpoint=endpoint,
            to=settings.sms_to or "",
            token=token,
            sender=settings.sms_from,
            timeout=settings.sms_timeout_seconds,
        )
    except ValueError as exc:
        warnings.append(f"canal 'sms' ignorado: {exc}")
