"""Caso de uso: criar e verificar alertas de preço.

Fluxo: para cada alerta ativo, executa a busca, aplica as regras, escolhe a
melhor oferta elegivel, grava um evento (com chave de deduplicacao) e enfileira
notificações no outbox. A mesma oferta na mesma faixa de preço nunca notifica
duas vezes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from dealhunter.adapters.notify.base import NotificationMessage, Notifier
from dealhunter.adapters.storage.repository import SqliteRepository, iso
from dealhunter.application.dto import QuerySpec, StoredAlert
from dealhunter.application.use_cases.search import SearchService
from dealhunter.domain.ids import stable_id
from dealhunter.domain.models import OfferView
from dealhunter.domain.ports.clock import Clock
from dealhunter.domain.value_objects.money import Money

PRICE_BUCKET_CENTS = 5_000  # faixas de R$ 50 para deduplicacao
MAX_ACTIVE_ALERTS = 50
MAX_CHANNELS_PER_ALERT = 5
MAX_LABEL_CHARS = 200
MAX_QUERY_CHARS = 500
_ALLOWED_CHANNELS = {"console", "email"}
_CHANNEL = re.compile(r"^[a-z][a-z0-9_-]{0,30}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True, slots=True)
class AlertOutcome:
    alert_id: int
    label: str
    matched: bool
    offer_id: str | None = None
    price: Money | None = None
    channels_sent: tuple[tuple[str, bool, str | None], ...] = ()
    note: str = ""


def create_alert(
    repository: SqliteRepository,
    *,
    query: str,
    spec: QuerySpec,
    max_price_cents: int | None,
    min_discount_pct: float | None,
    channels: list[str],
    label: str | None,
    now: datetime,
    max_active: int = MAX_ACTIVE_ALERTS,
) -> int:
    """Cria um alerta; exige ao menos uma regra (preço ou desconto)."""
    if max_price_cents is None and min_discount_pct is None:
        raise ValueError("um alerta precisa de --max-price e/ou --discount")
    if max_price_cents is not None and max_price_cents < 0:
        raise ValueError("preço-alvo não pode ser negativo")
    if min_discount_pct is not None and not 0 <= min_discount_pct <= 100:
        raise ValueError("desconto deve estar entre 0 e 100")
    if not channels:
        raise ValueError("um alerta precisa de ao menos um canal de notificação")
    if len(channels) > MAX_CHANNELS_PER_ALERT:
        raise ValueError(f"um alerta aceita no máximo {MAX_CHANNELS_PER_ALERT} canais")

    normalized_channels: list[str] = []
    for channel in channels:
        name = channel.strip().lower()
        if not _CHANNEL.fullmatch(name) or name not in _ALLOWED_CHANNELS:
            raise ValueError(f"canal de notificação desconhecido ou inválido: {name[:32]}")
        if name not in normalized_channels:
            normalized_channels.append(name)

    clean_query = query.strip()
    if not clean_query or len(clean_query) > MAX_QUERY_CHARS:
        raise ValueError(f"a busca do alerta deve ter de 1 a {MAX_QUERY_CHARS} caracteres")
    clean_label = (label or clean_query).strip()
    if not clean_label or len(clean_label) > MAX_LABEL_CHARS:
        raise ValueError(f"o nome do alerta deve ter de 1 a {MAX_LABEL_CHARS} caracteres")
    if _CONTROL.search(clean_query) or _CONTROL.search(clean_label):
        raise ValueError("busca ou nome do alerta contém caracteres de controle")
    if repository.count_active_alerts() >= max_active:
        raise ValueError(f"limite de {max_active} alertas ativos atingido")

    return repository.create_alert(
        label=clean_label,
        query=clean_query,
        spec_json=spec.model_dump_json(),
        max_price_cents=max_price_cents,
        min_discount_pct=min_discount_pct,
        channels=normalized_channels,
        now=now,
    )


class AlertService:
    def __init__(
        self,
        *,
        repository: SqliteRepository,
        search: SearchService,
        notifier: Notifier,
        clock: Clock,
        max_per_hour: int = 30,
        max_active: int = MAX_ACTIVE_ALERTS,
    ) -> None:
        self._repo = repository
        self._search = search
        self._notifier = notifier
        self._clock = clock
        self._max_per_hour = max_per_hour
        self._max_active = max_active

    def create(
        self,
        *,
        query: str,
        spec: QuerySpec,
        max_price_cents: int | None,
        min_discount_pct: float | None,
        channels: list[str],
        label: str | None = None,
    ) -> int:
        return create_alert(
            self._repo,
            query=query,
            spec=spec,
            max_price_cents=max_price_cents,
            min_discount_pct=min_discount_pct,
            channels=channels,
            label=label,
            now=self._clock.now(),
            max_active=self._max_active,
        )

    async def check(self, alert_id: int | None = None) -> list[AlertOutcome]:
        alerts = self._repo.list_alerts(only_active=True)
        if alert_id is not None:
            alerts = [alert for alert in alerts if alert.id == alert_id]
            if not alerts:
                return [
                    AlertOutcome(
                        alert_id=alert_id,
                        label="",
                        matched=False,
                        note="alerta não encontrado ou pausado",
                    )
                ]

        outcomes: list[AlertOutcome] = []
        for alert in alerts:
            outcomes.append(await self._check_one(alert))
        return outcomes

    async def _check_one(self, alert: StoredAlert) -> AlertOutcome:
        spec = QuerySpec.model_validate_json(alert.spec_json)
        report = await self._search.search(spec)
        self._repo.touch_alert(alert.id, self._clock.now())

        best: OfferView | None = None
        reason = ""
        for view in report.views:
            matched, matched_reason = _matches(alert, view)
            if matched and (best is None or view.offer.final_price < best.offer.final_price):
                best, reason = view, matched_reason

        if best is None:
            return AlertOutcome(
                alert_id=alert.id,
                label=alert.label,
                matched=False,
                note="nenhuma oferta atingiu a regra",
            )

        bucket = best.offer.final_price.cents // PRICE_BUCKET_CENTS
        dedupe_key = stable_id("evt", str(alert.id), best.offer.id, str(bucket))
        event_id = self._repo.record_event(
            alert_id=alert.id,
            offer_id=best.offer.id,
            price_cents=best.offer.final_price.cents,
            reason=reason,
            dedupe_key=dedupe_key,
            now=self._clock.now(),
        )
        if event_id is None:
            return AlertOutcome(
                alert_id=alert.id,
                label=alert.label,
                matched=True,
                offer_id=best.offer.id,
                price=best.offer.final_price,
                note="já notificado para esta faixa de preço",
            )

        sent = await self._dispatch(alert, event_id, best, reason)
        return AlertOutcome(
            alert_id=alert.id,
            label=alert.label,
            matched=True,
            offer_id=best.offer.id,
            price=best.offer.final_price,
            channels_sent=tuple(sent),
            note=reason,
        )

    async def _dispatch(
        self, alert: StoredAlert, event_id: int, view: OfferView, reason: str
    ) -> list[tuple[str, bool, str | None]]:
        message = build_message(alert, view, reason)
        results: list[tuple[str, bool, str | None]] = []

        for channel in alert.channels:
            if not self._notifier.supports(channel):
                results.append((channel, False, "canal não disponível"))
                continue

            since = self._clock.now() - timedelta(hours=1)
            if self._repo.count_notifications_since(since) >= self._max_per_hour:
                results.append((channel, False, "limite de notificações por hora atingido"))
                continue

            notification_id = self._repo.enqueue_notification(
                event_id=event_id,
                channel=channel,
                destination=None,
                subject=message.subject,
                body=message.body,
                now=self._clock.now(),
            )
            ok, error = await self._notifier.send(channel, message)
            self._repo.mark_notification(
                notification_id,
                status="sent" if ok else "failed",
                error=error,
                now=self._clock.now(),
            )
            results.append((channel, ok, error))
        return results


def _matches(alert: StoredAlert, view: OfferView) -> tuple[bool, str]:
    if alert.max_price_cents is not None and view.offer.final_price.cents <= alert.max_price_cents:
        target = Money(alert.max_price_cents, view.offer.final_price.currency)
        return True, f"preço final {view.offer.final_price} atingiu a meta {target}"

    if alert.min_discount_pct is not None and view.stats and view.stats.sufficient_history:
        percentage = view.stats.discount_vs_average()
        if percentage >= alert.min_discount_pct:
            return True, f"{percentage}% abaixo da média histórica {view.stats.average}"

    return False, ""


def build_message(alert: StoredAlert, view: OfferView, reason: str) -> NotificationMessage:
    offer = view.offer
    product = view.product
    lines = [
        f"OFERTA ENCONTRADA - {alert.label}",
        "",
        f"Produto: {product.title}",
        f"Preço: {offer.price}",
    ]
    if offer.list_price:
        lines.append(f"Preço anterior anunciado pela loja: {offer.list_price}")
    if view.stats:
        lines.append(f"Média histórica ({view.stats.days_covered}d): {view.stats.average}")
        lines.append(f"Desconto vs média: {view.stats.discount_vs_average()}%")
        lines.append(f"Menor preço observado: {view.stats.minimum}")
    lines += [
        f"Frete: {offer.shipping if offer.shipping is not None else 'não informado'}",
        f"Preço final: {offer.final_price}",
        f"Loja: {view.store.name}" + (f" ({view.store.domain})" if view.store.domain else ""),
    ]
    if view.seller:
        lines.append(f"Vendedor: {view.seller.name}")
    if offer.coupon_code:
        lines.append(f"Cupom: {offer.coupon_code} (não validado)")
    lines += [
        f"Oportunidade (preço/frete/histórico): {view.deal_score:.0f}/100",
        "Confiabilidade: não avaliada nesta fase (análise antifraude na Fase 3)",
        f"Regra atendida: {reason}",
        f"Link: {offer.url}",
        f"Verificado em: {offer.collected_at.isoformat() if offer.collected_at else 'agora'}",
    ]
    return NotificationMessage(
        subject=f"[DealHunter] {product.title} por {offer.final_price}", body="\n".join(lines)
    )


def alert_age_hours(alert: StoredAlert, now: datetime) -> float:
    from datetime import UTC

    parsed = datetime.fromisoformat(alert.created_at)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return round((now - parsed).total_seconds() / 3600, 1)


def alert_created_at(_: StoredAlert) -> str:
    return iso(datetime.now())
