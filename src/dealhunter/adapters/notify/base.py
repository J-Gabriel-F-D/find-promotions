"""Contrato de notificação e despacho com fallback.

Canais são plugaveis. ``console`` sempre existe (util para testar e para quem
roda a CLI sem SMTP); ``email`` depende de configuração explicita.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class NotificationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class NotificationMessage:
    subject: str
    body: str
    destination: str | None = None


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
            return False, f"{type(exc).__name__}: {exc}"
        return True, None
