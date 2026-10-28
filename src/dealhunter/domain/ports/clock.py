"""Porta de tempo.

Tempo e sempre UTC internamente; a conversao para o fuso do usuário acontece
apenas na camada de apresentacao.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """Fonte de tempo injetável (permite testes determinísticos)."""

    def now(self) -> datetime:
        """Instante atual, sempre com timezone (UTC)."""
        ...


class SystemClock:
    """Relogio real do sistema."""

    __slots__ = ()

    def now(self) -> datetime:
        return datetime.now(UTC)


class FrozenClock:
    """Relogio fixo para testes."""

    __slots__ = ("_instant",)

    def __init__(self, instant: datetime) -> None:
        if instant.tzinfo is None:
            raise ValueError("FrozenClock exige datetime com timezone")
        self._instant = instant.astimezone(UTC)

    def now(self) -> datetime:
        return self._instant

    def advance(self, *, seconds: float = 0.0) -> datetime:
        from datetime import timedelta

        self._instant = self._instant + timedelta(seconds=seconds)
        return self._instant
