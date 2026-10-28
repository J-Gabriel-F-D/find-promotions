"""Caso de uso: listar cupons e simular sua aplicação.

A simulação é **local e declarada como tal**. Ela registra o que calculamos em
``coupon_validation`` com ``method='local_rules'``; não é uma confirmação da
loja e nunca altera o preço confirmado de uma oferta.
"""

from __future__ import annotations

from dealhunter.adapters.storage.repository import SqliteRepository
from dealhunter.application.dto import CouponCheck, CouponRow
from dealhunter.domain.ports.clock import Clock
from dealhunter.domain.value_objects.money import Money
from dealhunter.services import coupons as coupon_rules


class CouponService:
    def __init__(self, *, repository: SqliteRepository, clock: Clock) -> None:
        self._repo = repository
        self._clock = clock

    def list_coupons(
        self, *, store: str | None = None, include_expired: bool = False
    ) -> list[CouponRow]:
        return self._repo.list_coupons(
            now=self._clock.now(), store=store, include_expired=include_expired
        )

    def check(
        self,
        code: str,
        *,
        price: Money,
        shipping: Money | None = None,
        store: str | None = None,
    ) -> list[CouponCheck]:
        now = self._clock.now()
        rows = self._repo.find_coupons_by_code(code, store=store)
        outcomes: list[CouponCheck] = []
        for row in rows:
            evaluation = coupon_rules.evaluate(row.coupon, price=price, shipping=shipping, now=now)
            self._repo.record_coupon_validation(
                coupon_id=row.coupon.id,
                method="local_rules",
                applicable=evaluation.applicable,
                reason=evaluation.reason,
                price_cents=price.cents,
                now=now,
            )
            outcomes.append(
                CouponCheck(
                    coupon=row.coupon,
                    store_name=row.store_name,
                    store_domain=row.store_domain,
                    evaluation=evaluation,
                )
            )
        return sorted(
            outcomes,
            key=lambda item: (
                not item.evaluation.applicable,
                -item.evaluation.discount.cents,
                item.store_name,
            ),
        )
