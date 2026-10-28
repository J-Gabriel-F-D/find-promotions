"""Testes do bootstrap/migracoes do SQLite."""

from __future__ import annotations

from pathlib import Path

from dealhunter.adapters.storage.database import Database


def test_migrate_cria_schema(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    assert database.schema_version() is None

    result = database.migrate()
    assert "0001_init" in result.applied
    assert "0002_mvp" in result.applied
    assert database.schema_version() == "0002_mvp"
    assert database.integrity_check() is True


def test_migrate_e_idempotente(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    database.migrate()
    second = database.migrate()
    assert second.applied == ()


def test_tabela_de_auditoria_existe(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    database.migrate()
    with database.connect() as connection:
        tables = {
            row["name"]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "audit_log" in tables
    assert "schema_migration" in tables


def test_pragmas_aplicados(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    with database.connect() as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_banco_sem_migracao_nao_quebra(tmp_path: Path) -> None:
    database = Database(tmp_path / "nao-existe.db")
    assert database.schema_version() is None
    assert database.size_bytes() == 0
    assert database.integrity_check() is True
