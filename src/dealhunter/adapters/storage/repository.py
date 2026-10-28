"""Repositorio SQLite da Fase 1.

Todo o SQL vive aqui. O dominio e a aplicação nunca veem ``sqlite3``.
IDs são determinísticos, portanto ``INSERT ... ON CONFLICT`` torna a coleta
idempotente: rodar a mesma busca duas vezes não duplica produto/loja/oferta.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from dealhunter.adapters.storage.database import Database
from dealhunter.application.dto import OfferRow, PriceSample, StoredAlert
from dealhunter.domain.models import Offer, Product, Seller, Store

if TYPE_CHECKING:
    import sqlite3

    from dealhunter.domain.models import CollectedOffer

# Rechecagens do mesmo preço em menos de uma hora nao viram novas amostras:
# evita inflar o historico sem mudanca real de preco.
SNAPSHOT_MIN_INTERVAL_MINUTES = 60


def iso(moment: datetime) -> str:
    """Serializa datetime em ISO-8601 UTC (ordenavel lexicograficamente)."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def parse_iso(text: str) -> datetime:
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class OfferRecord:
    product: Product
    store: Store
    seller: Seller | None
    offer: Offer
    collected: CollectedOffer | None = None


class SqliteRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    # ------------------------------------------------------------------ escrita
    def save_batch(self, records: Sequence[OfferRecord], *, now: datetime) -> int:
        """Persiste produtos/lojas/ofertas e uma amostra de preço por oferta."""
        stamp = iso(now)
        with self._db.connect() as connection:
            for record in records:
                self._upsert_store(connection, record.store, stamp)
                if record.seller is not None:
                    self._upsert_seller(connection, record.seller, stamp)
                self._upsert_product(connection, record.product, stamp)
                self._upsert_offer(connection, record.offer, stamp)

                offer = record.offer
                if not self._should_record_snapshot(connection, offer, now):
                    continue
                connection.execute(
                    """
                    INSERT OR IGNORE INTO offer_snapshot (
                        offer_id, price_cents, list_price_cents, shipping_cents, currency,
                        installments, installment_cents, collected_at, source, source_url,
                        confidence
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        offer.id,
                        offer.price.cents,
                        offer.list_price.cents if offer.list_price else None,
                        offer.shipping.cents if offer.shipping is not None else None,
                        offer.price.currency,
                        offer.installments,
                        offer.installment_value.cents if offer.installment_value else None,
                        stamp,
                        offer.source,
                        offer.source_url,
                        offer.confidence,
                    ),
                )
        return len(records)

    def add_backfill(
        self,
        items: Sequence[tuple[OfferRecord, Sequence[tuple[int, int]]]],
        *,
        now: datetime,
    ) -> None:
        """Insere série historica declarada pela fonte (somente fontes demo).

        Cada item e ``(registro, [(dias_atras, preco_em_centavos), ...])``.
        """
        with self._db.connect() as connection:
            for record, history in items:
                for days_ago, price_cents in history:
                    # Ancorado ao meio-dia UTC: a mesma serie historica reaplicada
                    # em outra execucao cai no mesmo instante e nao duplica.
                    moment = (
                        (now - timedelta(days=days_ago))
                        .astimezone(UTC)
                        .replace(hour=12, minute=0, second=0, microsecond=0)
                    )
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO offer_snapshot (
                            offer_id, price_cents, shipping_cents, currency,
                            collected_at, source, source_url, confidence
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            record.offer.id,
                            price_cents,
                            record.offer.shipping.cents if record.offer.shipping else None,
                            record.offer.price.currency,
                            iso(moment),
                            f"{record.offer.source}:backfill",
                            record.offer.source_url,
                            0.5,
                        ),
                    )

    def _should_record_snapshot(
        self, connection: sqlite3.Connection, offer: Offer, now: datetime
    ) -> bool:
        """Evita inflar o histórico com rechecagens do mesmo preço.

        Se o preço não mudou desde a última amostra e ela é recente, nada é
        gravado. Mudança de preço é **sempre** registrada.
        """
        row = connection.execute(
            """
            SELECT price_cents, collected_at FROM offer_snapshot
            WHERE offer_id = ?
            ORDER BY collected_at DESC
            LIMIT 1
            """,
            (offer.id,),
        ).fetchone()
        if row is None:
            return True
        if row["price_cents"] != offer.price.cents:
            return True
        last = parse_iso(row["collected_at"])
        return (now - last) >= timedelta(minutes=SNAPSHOT_MIN_INTERVAL_MINUTES)

    def _upsert_store(self, connection: sqlite3.Connection, store: Store, stamp: str) -> None:
        connection.execute(
            """
            INSERT INTO store (id, name, domain, reputation, source, first_seen_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                name = excluded.name,
                last_seen_at = excluded.last_seen_at
            """,
            (store.id, store.name, store.domain, store.reputation, store.source, stamp, stamp),
        )

    def _upsert_seller(self, connection: sqlite3.Connection, seller: Seller, stamp: str) -> None:
        connection.execute(
            """
            INSERT INTO seller (
                id, store_id, name, rating, sales_count, source,
                first_seen_at, last_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                rating = COALESCE(excluded.rating, seller.rating),
                sales_count = COALESCE(excluded.sales_count, seller.sales_count),
                last_seen_at = excluded.last_seen_at
            """,
            (
                seller.id,
                seller.store_id,
                seller.name,
                seller.rating,
                seller.sales_count,
                seller.source,
                stamp,
                stamp,
            ),
        )

    def _upsert_product(self, connection: sqlite3.Connection, product: Product, stamp: str) -> None:
        connection.execute(
            """
            INSERT INTO product (
                id, title, brand, model, family, storage_gb, ram_gb, gtin, mpn,
                condition, identity_kind, identity_value, specs_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                title = excluded.title,
                specs_json = excluded.specs_json,
                updated_at = excluded.updated_at
            """,
            (
                product.id,
                product.title,
                product.brand,
                product.model,
                product.family,
                product.storage_gb,
                product.ram_gb,
                product.gtin,
                product.mpn,
                product.condition,
                product.identity_kind,
                product.identity_value,
                json.dumps(product.specs, ensure_ascii=False),
                stamp,
                stamp,
            ),
        )

    def _upsert_offer(self, connection: sqlite3.Connection, offer: Offer, stamp: str) -> None:
        connection.execute(
            """
            INSERT INTO offer (
                id, product_id, store_id, seller_id, url, source, source_url,
                currency, condition, availability, coupon_code, active,
                first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                product_id = excluded.product_id,
                seller_id = COALESCE(excluded.seller_id, offer.seller_id),
                availability = excluded.availability,
                coupon_code = COALESCE(excluded.coupon_code, offer.coupon_code),
                active = 1,
                last_seen_at = excluded.last_seen_at
            """,
            (
                offer.id,
                offer.product_id,
                offer.store_id,
                offer.seller_id,
                offer.url,
                offer.source,
                offer.source_url,
                offer.price.currency,
                offer.condition,
                offer.availability,
                offer.coupon_code,
                stamp,
                stamp,
            ),
        )

    # ------------------------------------------------------------------ leitura
    def find_products(self, term: str, *, limit: int = 10) -> list[tuple[str, str]]:
        like = f"%{term.strip()}%"
        with self._db.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, title FROM product
                WHERE title LIKE ? OR identity_value LIKE ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (like, like, limit),
            ).fetchall()
        return [(row["id"], row["title"]) for row in rows]

    def product_title(self, product_id: str) -> str | None:
        with self._db.connect() as connection:
            row = connection.execute(
                "SELECT title FROM product WHERE id = ?", (product_id,)
            ).fetchone()
        return str(row["title"]) if row else None

    def offers_for_product(self, product_id: str) -> list[OfferRow]:
        """Oferta + snapshot mais recente de cada loja."""
        with self._db.connect() as connection:
            rows = connection.execute(
                """
                SELECT o.id            AS offer_id,
                       o.product_id    AS product_id,
                       p.title         AS title,
                       s.name          AS store_name,
                       s.domain        AS store_domain,
                       se.name         AS seller_name,
                       se.rating       AS seller_rating,
                       o.url           AS url,
                       snap.price_cents,
                       snap.shipping_cents,
                       snap.currency,
                       snap.collected_at,
                       o.source,
                       o.source_url,
                       snap.confidence
                FROM offer o
                JOIN product p ON p.id = o.product_id
                JOIN store s ON s.id = o.store_id
                LEFT JOIN seller se ON se.id = o.seller_id
                JOIN offer_snapshot snap ON snap.id = (
                    SELECT id FROM offer_snapshot
                    WHERE offer_id = o.id
                    ORDER BY collected_at DESC, id DESC
                    LIMIT 1
                )
                WHERE o.product_id = ? AND o.active = 1
                ORDER BY snap.price_cents ASC
                """,
                (product_id,),
            ).fetchall()
        return [
            OfferRow(
                offer_id=row["offer_id"],
                product_id=row["product_id"],
                title=row["title"],
                store_name=row["store_name"],
                store_domain=row["store_domain"],
                seller_name=row["seller_name"],
                seller_rating=row["seller_rating"],
                url=row["url"],
                price_cents=row["price_cents"],
                shipping_cents=row["shipping_cents"],
                currency=row["currency"],
                collected_at=row["collected_at"],
                source=row["source"],
                source_url=row["source_url"],
                confidence=row["confidence"],
            )
            for row in rows
        ]

    def price_samples(
        self, product_id: str, *, days: int = 90, now: datetime | None = None
    ) -> list[PriceSample]:
        reference = now or datetime.now(UTC)
        cutoff = iso(reference - timedelta(days=days))
        with self._db.connect() as connection:
            rows = connection.execute(
                """
                SELECT snap.collected_at, snap.price_cents, snap.source
                FROM offer_snapshot snap
                JOIN offer o ON o.id = snap.offer_id
                WHERE o.product_id = ? AND snap.collected_at >= ?
                ORDER BY snap.collected_at ASC
                """,
                (product_id, cutoff),
            ).fetchall()
        return [
            PriceSample(
                collected_at=parse_iso(row["collected_at"]),
                price_cents=row["price_cents"],
                source=row["source"],
            )
            for row in rows
        ]

    def offer_product(self, offer_id: str) -> tuple[str, str] | None:
        """Devolve ``(product_id, titulo)`` de uma oferta."""
        with self._db.connect() as connection:
            row = connection.execute(
                """
                SELECT p.id AS product_id, p.title AS title
                FROM offer o JOIN product p ON p.id = o.product_id
                WHERE o.id = ?
                """,
                (offer_id,),
            ).fetchone()
        return (row["product_id"], row["title"]) if row else None

    def price_samples_for_offer(self, offer_id: str, *, days: int = 90) -> list[PriceSample]:
        cutoff = iso(datetime.now(UTC) - timedelta(days=days))
        with self._db.connect() as connection:
            rows = connection.execute(
                """
                SELECT collected_at, price_cents, source
                FROM offer_snapshot
                WHERE offer_id = ? AND collected_at >= ?
                ORDER BY collected_at ASC
                """,
                (offer_id, cutoff),
            ).fetchall()
        return [
            PriceSample(
                collected_at=parse_iso(row["collected_at"]),
                price_cents=row["price_cents"],
                source=row["source"],
            )
            for row in rows
        ]

    # ------------------------------------------------------------------ alertas
    def create_alert(
        self,
        *,
        label: str,
        query: str,
        spec_json: str,
        max_price_cents: int | None,
        min_discount_pct: float | None,
        channels: Sequence[str],
        now: datetime,
    ) -> int:
        with self._db.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO alert (label, query, spec_json, max_price_cents,
                                   min_discount_pct, channels_json, active, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    label,
                    query,
                    spec_json,
                    max_price_cents,
                    min_discount_pct,
                    json.dumps(list(channels)),
                    iso(now),
                ),
            )
            return int(cursor.lastrowid or 0)

    def list_alerts(self, *, only_active: bool = False) -> list[StoredAlert]:
        sql = "SELECT * FROM alert"
        if only_active:
            sql += " WHERE active = 1"
        sql += " ORDER BY id"
        with self._db.connect() as connection:
            rows = connection.execute(sql).fetchall()
        return [
            StoredAlert(
                id=row["id"],
                label=row["label"],
                query=row["query"],
                spec_json=row["spec_json"],
                max_price_cents=row["max_price_cents"],
                min_discount_pct=row["min_discount_pct"],
                channels=tuple(json.loads(row["channels_json"])),
                active=bool(row["active"]),
                created_at=row["created_at"],
                last_checked_at=row["last_checked_at"],
            )
            for row in rows
        ]

    def get_alert(self, alert_id: int) -> StoredAlert | None:
        return next((alert for alert in self.list_alerts() if alert.id == alert_id), None)

    def set_alert_active(self, alert_id: int, active: bool) -> bool:
        with self._db.connect() as connection:
            cursor = connection.execute(
                "UPDATE alert SET active = ? WHERE id = ?", (1 if active else 0, alert_id)
            )
            return cursor.rowcount > 0

    def delete_alert(self, alert_id: int) -> bool:
        with self._db.connect() as connection:
            cursor = connection.execute("DELETE FROM alert WHERE id = ?", (alert_id,))
            return cursor.rowcount > 0

    def touch_alert(self, alert_id: int, now: datetime) -> None:
        with self._db.connect() as connection:
            connection.execute(
                "UPDATE alert SET last_checked_at = ? WHERE id = ?", (iso(now), alert_id)
            )

    def record_event(
        self,
        *,
        alert_id: int,
        offer_id: str | None,
        price_cents: int | None,
        reason: str,
        dedupe_key: str,
        now: datetime,
    ) -> int | None:
        """Registra o evento; devolve ``None`` se ja existia (dedupe)."""
        with self._db.connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO alert_event
                    (alert_id, offer_id, price_cents, reason, dedupe_key, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (alert_id, offer_id, price_cents, reason, dedupe_key, iso(now)),
            )
            if cursor.rowcount == 0:
                return None
            return int(cursor.lastrowid or 0)

    # ------------------------------------------------------------------ outbox
    def enqueue_notification(
        self,
        *,
        event_id: int | None,
        channel: str,
        destination: str | None,
        subject: str,
        body: str,
        now: datetime,
    ) -> int:
        with self._db.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO notification
                    (event_id, channel, destination, subject, body, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?)
                """,
                (event_id, channel, destination, subject, body, iso(now)),
            )
            return int(cursor.lastrowid or 0)

    def mark_notification(
        self,
        notification_id: int,
        *,
        status: str,
        error: str | None = None,
        now: datetime | None = None,
    ) -> None:
        with self._db.connect() as connection:
            connection.execute(
                """
                UPDATE notification
                SET status = ?, attempts = attempts + 1, error = ?,
                    sent_at = CASE WHEN ? = 'sent' THEN ? ELSE sent_at END
                WHERE id = ?
                """,
                (
                    status,
                    error,
                    status,
                    iso(now or datetime.now(UTC)),
                    notification_id,
                ),
            )

    def pending_notifications(self, *, limit: int = 50) -> list[dict[str, object]]:
        with self._db.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM notification WHERE status = 'pending' ORDER BY id LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
