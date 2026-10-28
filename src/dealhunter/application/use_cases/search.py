"""Caso de uso: buscar ofertas, persistir, analisar e ranquear.

Orquestra, em ordem: coleta paralela -> filtros -> normalização -> persistencia
-> estatísticas de preço -> classificacao do desconto -> ranking.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime

from dealhunter.adapters.sources.base import CollectorRunner, SourceResult
from dealhunter.adapters.storage.repository import OfferRecord, SqliteRepository
from dealhunter.application.dto import HistoryPoint, HistoryReport, QuerySpec, SearchReport
from dealhunter.domain.models import OfferView
from dealhunter.domain.ports.clock import Clock
from dealhunter.domain.value_objects.money import Money
from dealhunter.services import coupons as coupon_service
from dealhunter.services import matching, ranking
from dealhunter.services.normalizer import ProductNormalizer
from dealhunter.services.pricing import Sample, assess_discount, compute_stats


class SearchService:
    def __init__(
        self,
        *,
        repository: SqliteRepository,
        runner: CollectorRunner,
        clock: Clock,
        normalizer: ProductNormalizer | None = None,
        history_days: int = 90,
    ) -> None:
        self._repo = repository
        self._runner = runner
        self._clock = clock
        self._normalizer = normalizer or ProductNormalizer()
        self._history_days = history_days

    async def search(self, spec: QuerySpec) -> SearchReport:
        started_wall = self._clock.now()
        started = time.perf_counter()

        results = await self._runner.run(spec)
        records, reasons = self._collect(spec, results, started_wall)
        self._persist(records, started_wall)

        views = self._build_views(records, started_wall)
        scored = ranking.score_views(views, now=started_wall)
        ordered = ranking.sort_views(scored, spec.sort)[: spec.limit]

        collected_total = sum(result.status.items for result in results)
        warnings = self._warnings(results, sum(reasons.values()))

        return SearchReport(
            spec=spec,
            views=tuple(ordered),
            sources=tuple(result.status for result in results),
            collected=collected_total,
            discarded=sum(reasons.values()),
            discard_reasons=dict(reasons),
            picks=ranking.select_picks(scored, now=started_wall),
            warnings=tuple(warnings),
            started_at=started_wall.astimezone(UTC).isoformat(timespec="seconds"),
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    # ------------------------------------------------------------------ interno
    def _collect(
        self, spec: QuerySpec, results: Sequence[SourceResult], now: datetime
    ) -> tuple[list[OfferRecord], Counter[str]]:
        records: list[OfferRecord] = []
        reasons: Counter[str] = Counter()

        for result in results:
            for collected in result.offers:
                reason = matching.evaluate(spec, collected)
                if reason is not None:
                    reasons[reason] += 1
                    continue

                if collected.collected_at is None:
                    collected = replace(collected, collected_at=now)

                product = self._normalizer.to_product(collected)
                store = self._normalizer.to_store(collected)
                seller = self._normalizer.to_seller(collected, store)
                offer = self._normalizer.to_offer(
                    collected, product=product, store=store, seller=seller
                )

                records.append(
                    OfferRecord(
                        product=product,
                        store=store,
                        seller=seller,
                        offer=offer,
                        collected=collected,
                        coupons=self._normalizer.to_coupons(collected, store=store, now=now),
                        promotion=self._normalizer.to_promotion(collected, offer=offer),
                        reviews=self._normalizer.to_reviews(
                            collected, product=product, store=store
                        ),
                    )
                )
        return records, reasons

    def _persist(self, records: list[OfferRecord], now: datetime) -> None:
        if not records:
            return
        self._repo.save_batch(records, now=now)

        backfill: list[tuple[OfferRecord, Sequence[tuple[int, int]]]] = [
            (record, record.collected.history)
            for record in records
            if record.collected is not None and record.collected.history
        ]
        if backfill:
            self._repo.add_backfill(backfill, now=now)

    def _build_views(self, records: list[OfferRecord], now: datetime) -> list[OfferView]:
        samples_cache: dict[str, list[Sample]] = {}
        views: list[OfferView] = []

        for record in records:
            product_id = record.product.id
            if product_id not in samples_cache:
                samples_cache[product_id] = [
                    Sample(collected_at=sample.collected_at, price_cents=sample.price_cents)
                    for sample in self._repo.price_samples(
                        product_id, days=self._history_days, now=now
                    )
                ]
            # Estatísticas são recalculadas por oferta: "posição no histórico"
            # depende do preço atual de cada loja, não do primeiro item do grupo.
            stats = compute_stats(
                samples_cache[product_id],
                current_cents=record.offer.price.cents,
                currency=record.offer.price.currency,
            )

            discount = assess_discount(
                current=record.offer.price,
                list_price=record.offer.list_price,
                stats=stats,
            )
            evaluations = coupon_service.evaluate_all(
                record.coupons,
                price=record.offer.price,
                shipping=record.offer.shipping,
                now=now,
            )
            views.append(
                OfferView(
                    offer=record.offer,
                    product=record.product,
                    store=record.store,
                    seller=record.seller,
                    stats=stats,
                    discount=discount,
                    deal_score=0.0,
                    coupons=evaluations,
                    best_coupon=coupon_service.best_evaluation(evaluations),
                    promotion=record.promotion,
                    reviews=record.reviews,
                )
            )
        return views

    def _warnings(self, results: Sequence[SourceResult], discarded: int) -> list[str]:
        warnings: list[str] = []
        for result in results:
            status = result.status
            if status.status == "error":
                warnings.append(f"{status.label}: indisponível ({status.error})")
            elif status.status == "timeout":
                warnings.append(f"{status.label}: tempo limite excedido")
            elif status.status == "empty":
                warnings.append(f"{status.label}: nenhuma oferta encontrada")
            if status.source_id == "fixture":
                warnings.append(
                    "Dados de demonstração (fonte 'fixture') incluídos: "
                    "os preços NÃO representam ofertas reais."
                )
        if discarded:
            warnings.append(
                f"{discarded} oferta(s) descartada(s) pelos filtros; "
                "veja os motivos no resumo das fontes."
            )
        return warnings


class HistoryService:
    """Resolve um produto/oferta e devolve série historica + estatísticas."""

    def __init__(
        self,
        *,
        repository: SqliteRepository,
        clock: Clock,
        default_days: int = 90,
    ) -> None:
        self._repo = repository
        self._clock = clock
        self._default_days = default_days

    def build(
        self, term: str, *, days: int | None = None
    ) -> tuple[HistoryReport | None, list[str]]:
        window = days or self._default_days
        warnings: list[str] = []

        resolved: tuple[str, str] | None
        if term.startswith("off_"):
            resolved = self._repo.offer_product(term)
            if resolved is None:
                return None, [f"oferta não encontrada: {term}"]
        else:
            matches = self._repo.find_products(term)
            if not matches:
                return None, [f"nenhum produto encontrado para: {term}"]
            if len(matches) > 1:
                warnings.append(
                    f"{len(matches)} produtos correspondem a '{term}'; usando o mais recente. "
                    "Use o ID para escolher outro."
                )
            resolved = (matches[0][0], matches[0][1])

        product_id, title = resolved
        samples = self._repo.price_samples(product_id, days=window, now=self._clock.now())
        if not samples:
            return (
                HistoryReport(
                    product_id=product_id,
                    product_title=title,
                    points=(),
                    stats=None,
                    offers=tuple(self._repo.offers_for_product(product_id)),
                    days=window,
                    warnings=tuple(warnings + ["nenhuma amostra de preço na janela"]),
                ),
                warnings,
            )

        current = samples[-1].price_cents
        stats = compute_stats(
            [Sample(s.collected_at, s.price_cents) for s in samples],
            current_cents=current,
        )
        points = tuple(
            HistoryPoint(
                collected_at=sample.collected_at.astimezone(UTC).isoformat(timespec="seconds"),
                price=Money(sample.price_cents),
                source=sample.source,
            )
            for sample in samples
        )

        return (
            HistoryReport(
                product_id=product_id,
                product_title=title,
                points=points,
                stats=stats,
                offers=tuple(self._repo.offers_for_product(product_id)),
                days=window,
                warnings=tuple(warnings),
            ),
            warnings,
        )
