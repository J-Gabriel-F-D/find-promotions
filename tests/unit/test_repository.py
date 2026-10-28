"""Testes do repositorio SQLite."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from dealhunter.adapters.storage.database import Database
from dealhunter.adapters.storage.repository import SqliteRepository


class TestPersistencia:
    def test_salvar_e_idempotente(self, database: Database, make_offer_record, clock) -> None:
        repo = SqliteRepository(database)
        record = make_offer_record(price_cents=150_000)

        repo.save_batch([record], now=clock.now())
        repo.save_batch([record], now=clock.now())

        with database.connect() as connection:
            offers = connection.execute("SELECT COUNT(*) FROM offer").fetchone()[0]
            products = connection.execute("SELECT COUNT(*) FROM product").fetchone()[0]
            snapshots = connection.execute("SELECT COUNT(*) FROM offer_snapshot").fetchone()[0]

        assert offers == 1
        assert products == 1
        # Mesmo instante + mesmo preco: a unique evita duplicar a amostra.
        assert snapshots == 1

    def test_coletas_em_instantes_diferentes_geram_historico(
        self, database: Database, make_offer_record, clock
    ) -> None:
        repo = SqliteRepository(database)
        repo.save_batch([make_offer_record(price_cents=150_000)], now=clock.now())
        repo.save_batch(
            [make_offer_record(price_cents=140_000)], now=clock.now() + timedelta(days=1)
        )

        record = make_offer_record(price_cents=140_000)
        samples = repo.price_samples(record.product.id, now=clock.now() + timedelta(days=1))
        assert [sample.price_cents for sample in samples] == [150_000, 140_000]

    def test_rechecagem_do_mesmo_preco_nao_infla_historico(
        self, database: Database, make_offer_record, clock
    ) -> None:
        repo = SqliteRepository(database)
        record = make_offer_record(price_cents=150_000)
        for minutes in (0, 5, 30):
            repo.save_batch([record], now=clock.now() + timedelta(minutes=minutes))

        samples = repo.price_samples(record.product.id, now=clock.now())
        assert len(samples) == 1

        # Depois da janela minima, a mesma cotacao volta a ser registrada.
        repo.save_batch([record], now=clock.now() + timedelta(minutes=90))
        assert len(repo.price_samples(record.product.id, now=clock.now())) == 2

    def test_mudanca_de_preco_sempre_entra_no_historico(
        self, database: Database, make_offer_record, clock
    ) -> None:
        repo = SqliteRepository(database)
        first = make_offer_record(price_cents=150_000)
        repo.save_batch([first], now=clock.now())
        repo.save_batch(
            [make_offer_record(price_cents=145_000)], now=clock.now() + timedelta(minutes=1)
        )

        samples = repo.price_samples(first.product.id, now=clock.now())
        assert [sample.price_cents for sample in samples] == [150_000, 145_000]

    def test_backfill_adiciona_serie_sem_duplicar(
        self, database: Database, make_offer_record, clock
    ) -> None:
        repo = SqliteRepository(database)
        record = make_offer_record(price_cents=150_000)
        repo.save_batch([record], now=clock.now())
        repo.add_backfill([(record, [(30, 180_000), (10, 160_000)])], now=clock.now())
        repo.add_backfill([(record, [(30, 180_000)])], now=clock.now())

        samples = repo.price_samples(record.product.id, now=clock.now())
        assert len(samples) == 3

    def test_backfill_e_idempotente_entre_execucoes(
        self, database: Database, make_offer_record, clock
    ) -> None:
        repo = SqliteRepository(database)
        record = make_offer_record(price_cents=150_000)
        repo.save_batch([record], now=clock.now())
        repo.add_backfill([(record, [(30, 180_000)])], now=clock.now())
        # Execucao seguinte, horas depois: a ancora historica nao pode duplicar.
        repo.add_backfill([(record, [(30, 180_000)])], now=clock.now() + timedelta(hours=7))

        samples = repo.price_samples(record.product.id, now=clock.now())
        assert [sample.price_cents for sample in samples] == [180_000, 150_000]

    def test_offers_for_product_traz_loja_e_snapshot_mais_recente(
        self, database: Database, make_offer_record, clock
    ) -> None:
        repo = SqliteRepository(database)
        repo.save_batch(
            [make_offer_record(price_cents=150_000, store_name="Loja A")], now=clock.now()
        )
        rows = repo.offers_for_product(make_offer_record(price_cents=150_000).product.id)
        assert len(rows) == 1
        assert rows[0].store_name == "Loja A"
        assert rows[0].price_cents == 150_000
        assert rows[0].shipping_cents == 0

    def test_busca_produto_por_termo(self, database: Database, make_offer_record, clock) -> None:
        repo = SqliteRepository(database)
        repo.save_batch([make_offer_record(price_cents=150_000)], now=clock.now())
        assert repo.find_products("redmi")
        assert repo.find_products("produto inexistente") == []

    def test_offer_product_resolve_oferta(
        self, database: Database, make_offer_record, clock
    ) -> None:
        repo = SqliteRepository(database)
        record = make_offer_record(price_cents=150_000)
        repo.save_batch([record], now=clock.now())
        resolved = repo.offer_product(record.offer.id)
        assert resolved is not None
        assert resolved[0] == record.product.id


class TestAlertas:
    def _create(self, repo: SqliteRepository, now: datetime) -> int:
        return repo.create_alert(
            label="Redmi",
            query="redmi",
            spec_json='{"product": "redmi"}',
            max_price_cents=160_000,
            min_discount_pct=None,
            channels=["console"],
            now=now,
        )

    def test_crud_de_alertas(self, database: Database, clock) -> None:
        repo = SqliteRepository(database)
        alert_id = self._create(repo, clock.now())

        alerts = repo.list_alerts()
        assert [alert.id for alert in alerts] == [alert_id]
        assert alerts[0].channels == ("console",)
        assert alerts[0].active is True

        assert repo.set_alert_active(alert_id, False) is True
        assert repo.list_alerts(only_active=True) == []
        assert repo.set_alert_active(alert_id, True) is True

        repo.touch_alert(alert_id, clock.now())
        assert repo.list_alerts()[0].last_checked_at is not None

        assert repo.delete_alert(alert_id) is True
        assert repo.delete_alert(alert_id) is False
        assert repo.list_alerts() == []

    def test_evento_deduplicado_por_chave(self, database: Database, clock) -> None:
        repo = SqliteRepository(database)
        alert_id = self._create(repo, clock.now())

        first = repo.record_event(
            alert_id=alert_id,
            offer_id="off_x",
            price_cents=150_000,
            reason="preco",
            dedupe_key="evt_1",
            now=clock.now(),
        )
        second = repo.record_event(
            alert_id=alert_id,
            offer_id="off_x",
            price_cents=150_000,
            reason="preco",
            dedupe_key="evt_1",
            now=clock.now(),
        )
        assert isinstance(first, int)
        assert second is None

    def test_outbox_marca_envio(self, database: Database, clock) -> None:
        repo = SqliteRepository(database)
        notification_id = repo.enqueue_notification(
            event_id=None,
            channel="console",
            destination=None,
            subject="teste",
            body="corpo",
            now=clock.now(),
        )
        assert len(repo.pending_notifications()) == 1

        repo.mark_notification(notification_id, status="sent", now=clock.now())
        assert repo.pending_notifications() == []

    def test_evento_de_alerta_removido_em_cascata(self, database: Database, clock) -> None:
        repo = SqliteRepository(database)
        alert_id = self._create(repo, clock.now())
        repo.record_event(
            alert_id=alert_id,
            offer_id="off_x",
            price_cents=1,
            reason="r",
            dedupe_key="evt_cascade",
            now=clock.now(),
        )
        repo.delete_alert(alert_id)
        with database.connect() as connection:
            remaining = connection.execute("SELECT COUNT(*) FROM alert_event").fetchone()[0]
        assert remaining == 0


def test_banco_sem_migracao_falha_ao_escrever(tmp_path) -> None:
    import sqlite3

    database = Database(tmp_path / "vazio.db")
    repo = SqliteRepository(database)
    with pytest.raises(sqlite3.OperationalError):
        repo.list_alerts()


def test_datas_utc_sao_ordenaveis(database: Database, make_offer_record, clock) -> None:
    repo = SqliteRepository(database)
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    repo.save_batch([make_offer_record(price_cents=1)], now=now)
    repo.save_batch([make_offer_record(price_cents=2)], now=now + timedelta(hours=1))
    samples = repo.price_samples(make_offer_record(price_cents=1).product.id, now=now)
    assert [sample.price_cents for sample in samples] == [1, 2]
