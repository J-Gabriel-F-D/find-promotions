"""Caso de uso: criar e verificar alertas de preço.

Fluxo: para cada alerta ativo, executa a busca, aplica as regras, escolhe a
melhor oferta elegivel, grava um evento (com chave de deduplicacao) e enfileira
notificações no outbox. A mesma oferta na mesma faixa de preço nunca notifica
duas vezes.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timedelta

from dealhunter.adapters.notify.base import NotificationMessage, Notifier
from dealhunter.adapters.storage.repository import SqliteRepository, iso
from dealhunter.application.dto import AlertRule, QuerySpec, StoredAlert
from dealhunter.application.use_cases.search import SearchService
from dealhunter.domain.ids import stable_id
from dealhunter.domain.models import TRUST_DISCLAIMER, OfferView
from dealhunter.domain.ports.clock import Clock
from dealhunter.domain.value_objects.money import Money

PRICE_BUCKET_CENTS = 5_000  # faixas de R$ 50 para deduplicacao
MAX_ACTIVE_ALERTS = 50
MAX_CHANNELS_PER_ALERT = 5
MAX_LABEL_CHARS = 200
MAX_QUERY_CHARS = 500
_ALLOWED_CHANNELS = {"console", "email", "whatsapp", "sms"}
_CHANNEL = re.compile(r"^[a-z][a-z0-9_-]{0,30}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_RISK_ORDER = {"low": 0, "moderate": 1, "elevated": 2}


@dataclass(frozen=True, slots=True)
class AlertOutcome:
    alert_id: int
    label: str
    matched: bool
    offer_id: str | None = None
    price: Money | None = None
    channels_sent: tuple[tuple[str, bool, str | None], ...] = ()
    note: str = ""
    trust_score: float | None = None
    risk_band: str | None = None
    analysis_confidence: float | None = None
    discount_classification: str | None = None
    # Procedência da oferta: todo fato numérico precisa ser rastreável.
    source: str | None = None
    source_url: str | None = None
    offer_url: str | None = None
    collected_at: str | None = None
    confidence: float | None = None


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
    rule: AlertRule | None = None,
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
    if rule is not None and rule.is_empty:
        rule = None

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
        rule=rule,
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
        rule: AlertRule | None = None,
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
            rule=rule,
        )

    async def check(
        self,
        alert_id: int | None = None,
        *,
        skip_alert_ids: Collection[int] | None = None,
    ) -> list[AlertOutcome]:
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
        if skip_alert_ids:
            skipped = set(skip_alert_ids)
            alerts = [alert for alert in alerts if alert.id not in skipped]

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
        source, source_url, offer_url, collected_at, confidence = _offer_fields(best)
        if event_id is None:
            trust_score, risk_band, analysis_confidence, discount = _trust_fields(best)
            return AlertOutcome(
                alert_id=alert.id,
                label=alert.label,
                matched=True,
                offer_id=best.offer.id,
                price=best.offer.final_price,
                note="já notificado para esta faixa de preço",
                trust_score=trust_score,
                risk_band=risk_band,
                analysis_confidence=analysis_confidence,
                discount_classification=discount,
                source=source,
                source_url=source_url,
                offer_url=offer_url,
                collected_at=collected_at,
                confidence=confidence,
            )

        sent = await self._dispatch(alert, event_id, best, reason)
        trust_score, risk_band, analysis_confidence, discount = _trust_fields(best)
        return AlertOutcome(
            alert_id=alert.id,
            label=alert.label,
            matched=True,
            offer_id=best.offer.id,
            price=best.offer.final_price,
            channels_sent=tuple(sent),
            note=reason,
            trust_score=trust_score,
            risk_band=risk_band,
            analysis_confidence=analysis_confidence,
            discount_classification=discount,
            source=source,
            source_url=source_url,
            offer_url=offer_url,
            collected_at=collected_at,
            confidence=confidence,
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


def _offer_fields(view: OfferView) -> tuple[str, str, str, str | None, float]:
    offer = view.offer
    return (
        offer.source,
        offer.source_url,
        offer.url,
        offer.collected_at.isoformat() if offer.collected_at else None,
        offer.confidence,
    )


def _trust_fields(view: OfferView) -> tuple[float | None, str | None, float | None, str]:
    trust = view.trust
    return (
        round(trust.score, 1) if trust else None,
        trust.risk_band if trust else None,
        round(trust.analysis_confidence, 3) if trust else None,
        view.discount.classification,
    )


def _matches(alert: StoredAlert, view: OfferView) -> tuple[bool, str]:
    base: list[str] = []
    if alert.max_price_cents is not None and view.offer.final_price.cents <= alert.max_price_cents:
        target = Money(alert.max_price_cents, view.offer.final_price.currency)
        base.append(f"preço final {view.offer.final_price} atingiu a meta {target}")

    if alert.min_discount_pct is not None and view.stats and view.stats.sufficient_history:
        percentage = view.stats.discount_vs_average()
        if percentage >= alert.min_discount_pct:
            base.append(f"{percentage}% abaixo da média histórica {view.stats.average}")

    if not base:
        return False, ""

    rule = alert.rule
    if rule.is_empty:
        return True, " ou ".join(base)

    trust = view.trust
    if trust is None:
        return False, ""

    gates: list[str] = []
    if rule.min_trust is not None:
        if trust.score < rule.min_trust:
            return False, ""
        gates.append(f"confiança {trust.score:.0f}/100 >= {rule.min_trust:g}")
    if rule.max_risk is not None:
        # "Sem dados" não é o mesmo que risco baixo: a regra conservadora exige
        # uma faixa observável em vez de presumir segurança.
        if trust.risk_band == "insufficient_data" or (
            _RISK_ORDER[trust.risk_band] > _RISK_ORDER[rule.max_risk]
        ):
            return False, ""
        gates.append(f"risco observado {trust.risk_band} <= {rule.max_risk}")
    if rule.require_real_discount:
        if view.discount.classification != "likely_real":
            return False, ""
        gates.append("desconto corroborado pelo histórico")
    if rule.min_analysis_confidence is not None:
        if trust.analysis_confidence < rule.min_analysis_confidence:
            return False, ""
        gates.append(
            f"cobertura da análise {trust.analysis_confidence:.0%} "
            f">= {rule.min_analysis_confidence:.0%}"
        )

    return True, " ou ".join(base) + " | " + "; ".join(gates)


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
    lines.append(f"Oportunidade (preço/frete/histórico): {view.deal_score:.0f}/100")
    if view.trust:
        lines += [
            f"Confiabilidade (probabilística): {view.trust.score:.0f}/100; "
            f"risco: {view.trust.risk_band}; "
            f"cobertura da análise: {view.trust.analysis_confidence:.0%}",
            f"Desconto: {view.discount.classification} ({view.discount.evidence})",
            TRUST_DISCLAIMER,
        ]
    else:
        lines.append("Confiabilidade: não avaliada para esta oferta")
    lines += [
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
