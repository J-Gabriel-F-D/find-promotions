"""Contrato dos adapters de coleta e executor resiliente.

Cada fonte e um modulo independente. Se uma falhar (timeout, layout novo, API
fora do ar), as demais continuam e o resultado parcial e devolvido.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from dealhunter.application.dto import QuerySpec
from dealhunter.domain.models import CollectedOffer, SourceStatus

Capability = Literal["search", "detail", "coupons", "reviews"]


@dataclass(frozen=True, slots=True)
class SourceResult:
    status: SourceStatus
    offers: tuple[CollectedOffer, ...]


@runtime_checkable
class SourceAdapter(Protocol):
    """Uma fonte de dados (API oficial, feed ou fixture)."""

    id: str
    label: str
    capabilities: frozenset[Capability]

    async def search(self, spec: QuerySpec) -> list[CollectedOffer]:
        """Busca ofertas. Deve levantar exceção em falha; o runner trata."""
        ...


class CollectorRunner:
    """Executa os adapters em paralelo, com timeout e isolamento de falhas."""

    def __init__(
        self,
        adapters: list[SourceAdapter],
        *,
        timeout: float = 20.0,
        max_concurrency: int = 6,
    ) -> None:
        self._adapters = adapters
        self._timeout = timeout
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def run(self, spec: QuerySpec) -> list[SourceResult]:
        if not self._adapters:
            return []
        tasks = [self._run_one(adapter, spec) for adapter in self._adapters]
        return list(await asyncio.gather(*tasks))

    async def _run_one(self, adapter: SourceAdapter, spec: QuerySpec) -> SourceResult:
        started = time.perf_counter()
        async with self._semaphore:
            try:
                offers = await asyncio.wait_for(adapter.search(spec), timeout=self._timeout)
            except TimeoutError:
                return SourceResult(
                    status=SourceStatus(
                        source_id=adapter.id,
                        label=adapter.label,
                        status="timeout",
                        duration_ms=_elapsed_ms(started),
                        error=f"tempo limite de {self._timeout:g}s excedido",
                    ),
                    offers=(),
                )
            except Exception as exc:  # noqa: BLE001 - falha de um adapter não pode derrubar a busca
                return SourceResult(
                    status=SourceStatus(
                        source_id=adapter.id,
                        label=adapter.label,
                        status="error",
                        duration_ms=_elapsed_ms(started),
                        error=f"{type(exc).__name__}: {exc}",
                    ),
                    offers=(),
                )

        status: Literal["ok", "empty"] = "ok" if offers else "empty"
        return SourceResult(
            status=SourceStatus(
                source_id=adapter.id,
                label=adapter.label,
                status=status,
                items=len(offers),
                duration_ms=_elapsed_ms(started),
            ),
            offers=tuple(offers),
        )


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
