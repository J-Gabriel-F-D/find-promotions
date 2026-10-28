"""Portas (interfaces) do dominio.

Adapters implementam estes Protocolos; o dominio nunca importa implementacoes.
"""

from __future__ import annotations

from dealhunter.domain.ports.clock import Clock, FrozenClock, SystemClock

__all__ = ["Clock", "FrozenClock", "SystemClock"]
