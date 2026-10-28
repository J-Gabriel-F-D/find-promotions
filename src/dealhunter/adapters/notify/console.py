"""Canal de console: visivel no terminal e sem dependencia externa."""

from __future__ import annotations

from collections.abc import Callable

from dealhunter.adapters.notify.base import NotificationMessage


class ConsoleChannel:
    id = "console"
    label = "Console"

    def __init__(self, printer: Callable[[str], None]) -> None:
        self._print = printer

    def send(self, message: NotificationMessage) -> None:
        self._print(message.body)
