"""Caso de uso: listar promoções com janela temporal."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from dealhunter.adapters.storage.repository import SqliteRepository
from dealhunter.application.dto import PromotionRow
from dealhunter.domain.ports.clock import Clock


@dataclass(frozen=True, slots=True)
class PromotionReport:
    now: datetime
    rows: tuple[PromotionRow, ...]
    include_expired: bool = False
    warnings: tuple[str, ...] = field(default_factory=tuple)


class PromotionService:
    def __init__(self, *, repository: SqliteRepository, clock: Clock) -> None:
        self._repo = repository
        self._clock = clock

    def list(
        self,
        *,
        include_expired: bool = False,
        source: str | None = None,
        expiring_hours: int | None = None,
    ) -> PromotionReport:
        now = self._clock.now()
        rows = self._repo.list_promotions(
            now=now,
            include_expired=include_expired,
            source=source,
            expiring_hours=expiring_hours,
        )
        warnings: list[str] = []
        if any(row.promotion.source == "fixture" for row in rows):
            warnings.append(
                "Dados de demonstração (fonte 'fixture') incluídos: "
                "as promoções NÃO representam ofertas reais."
            )
        return PromotionReport(
            now=now,
            rows=tuple(rows),
            include_expired=include_expired,
            warnings=tuple(warnings),
        )
