"""Casos de uso de privacidade e retenção de dados locais."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from dealhunter.adapters.storage.repository import SqliteRepository


@dataclass(frozen=True, slots=True)
class PrivacyExport:
    generated_at: datetime
    alerts: tuple[dict[str, Any], ...]
    events: tuple[dict[str, Any], ...]
    notifications: tuple[dict[str, Any], ...]
    counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class RetentionResult:
    days: int
    cutoff: datetime
    applied: bool
    counts: dict[str, int]


class PrivacyService:
    """Exporta, apaga e aplica retenção sobre dados pessoais locais.

    O catálogo público de produtos/ofertas não é tratado como dado pessoal e
    permanece no banco. O que sai daqui são alertas, eventos e metadados de
    notificação criados pelo próprio usuário.
    """

    def __init__(self, repository: SqliteRepository) -> None:
        self._repo = repository

    def export(self, now: datetime) -> PrivacyExport:
        raw = self._repo.export_personal_data()
        alerts = tuple(self._normalize_alert(item) for item in raw["alerts"])
        return PrivacyExport(
            generated_at=now,
            alerts=alerts,
            events=tuple(raw["events"]),
            notifications=tuple(raw["notifications"]),
            counts={
                "alerts": len(alerts),
                "events": len(raw["events"]),
                "notifications": len(raw["notifications"]),
            },
        )

    def forget(self) -> dict[str, int]:
        counts = self._repo.purge_personal_data()
        self._repo.vacuum()
        return counts

    def retention(self, *, days: int, now: datetime, apply: bool) -> RetentionResult:
        if not 1 <= days <= 3_650:
            raise ValueError("dias de retenção devem estar entre 1 e 3650")
        cutoff = now - timedelta(days=days)
        counts = (
            self._repo.delete_personal_records_before(cutoff)
            if apply
            else self._repo.count_personal_records_before(cutoff)
        )
        if apply:
            self._repo.vacuum()
        return RetentionResult(days=days, cutoff=cutoff, applied=apply, counts=counts)

    @staticmethod
    def _normalize_alert(item: dict[str, object]) -> dict[str, Any]:
        normalized: dict[str, Any] = dict(item)
        normalized["active"] = bool(item.get("active"))
        channels = item.get("channels")
        if isinstance(channels, str):
            try:
                parsed = json.loads(channels)
            except ValueError:
                parsed = []
            normalized["channels"] = parsed if isinstance(parsed, list) else []
        return normalized
