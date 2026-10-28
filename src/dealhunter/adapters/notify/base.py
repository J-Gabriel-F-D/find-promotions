"""Contrato de notificação e despacho com fallback.

Canais são plugaveis. ``console`` sempre existe (util para testar e para quem
roda a CLI sem SMTP); ``email`` depende de configuração explicita.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from dealhunter.runtime.logging import redact_text

MAX_SUBJECT_CHARS = 200
MAX_BODY_CHARS = 50_000
_EMAIL = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)


class NotificationError(RuntimeError):
    pass


def is_valid_email(address: str | None) -> bool:
    """Validação pragmática de destinatário (sem header injection)."""
    if not address or len(address) > 254:
        return False
    if any(char in address for char in "\r\n\x00<> ,;"):
        return False
    return bool(_EMAIL.fullmatch(address.strip()))


@dataclass(frozen=True, slots=True)
class NotificationMessage:
    subject: str
    body: str
    destination: str | None = None

    def __post_init__(self) -> None:
        if not self.subject.strip() or len(self.subject) > MAX_SUBJECT_CHARS:
            raise ValueError("assunto de notificação inválido ou muito longo")
        if "\r" in self.subject or "\n" in self.subject or "\x00" in self.subject:
            raise ValueError("assunto de notificação não pode conter quebras de linha")
        if len(self.body) > MAX_BODY_CHARS or "\x00" in self.body:
            raise ValueError("corpo de notificação inválido ou muito longo")


@runtime_checkable
class NotificationChannel(Protocol):
    id: str
    label: str

    def send(self, message: NotificationMessage) -> None:
        """Envia de forma bloqueante; o despachante isola em thread."""
        ...


class Notifier:
    def __init__(self, channels: dict[str, NotificationChannel]) -> None:
        self._channels = channels

    @property
    def available(self) -> tuple[str, ...]:
        return tuple(sorted(self._channels))

    def supports(self, channel_id: str) -> bool:
        return channel_id in self._channels

    async def send(self, channel_id: str, message: NotificationMessage) -> tuple[bool, str | None]:
        channel = self._channels.get(channel_id)
        if channel is None:
            return False, f"canal não configurado: {channel_id}"

        try:
            await asyncio.to_thread(channel.send, message)
        except Exception as exc:  # noqa: BLE001 - falha de canal não pode derrubar o alerta
            detail = redact_text(str(exc))
            return False, f"{type(exc).__name__}: {detail}"
        return True, None
