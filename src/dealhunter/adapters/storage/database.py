"""Bootstrap do SQLite e executor de migrações.

Por que SQLite: a aplicação roda na maquina do usuário, sem servidor e sem
Docker. WAL + ``busy_timeout`` atendem com folga o volume típico (dezenas de
milhares de ofertas). A camada de repositorio isola o SQL, permitindo migrar
para PostgreSQL sem tocar no dominio.

Convencoes
----------
* Dinheiro em **centavos inteiros**; datas em ISO-8601 UTC (texto).
* Migrações são arquivos ``NNNN_nome.sql`` aplicados em ordem e registrados em
  ``schema_migration``. Elas devem ser idempotentes (``IF NOT EXISTS``), porque
  ``executescript`` do SQLite faz commit implicito antes de executar.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "data" / "migrations"
SCHEMA_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migration (
    version     TEXT PRIMARY KEY,
    applied_at  TEXT NOT NULL
)
"""


@dataclass(frozen=True, slots=True)
class MigrationResult:
    applied: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return bool(self.applied)


class Database:
    """Fachada fina sobre o arquivo SQLite."""

    def __init__(self, path: Path, *, migrations_dir: Path | None = None) -> None:
        self._path = Path(path)
        self._migrations_dir = migrations_dir or MIGRATIONS_DIR

    # ------------------------------------------------------------------ estado
    @property
    def path(self) -> Path:
        return self._path

    @property
    def exists(self) -> bool:
        return self._path.exists()

    def size_bytes(self) -> int:
        if not self.exists:
            return 0
        total = self._path.stat().st_size
        for suffix in ("-wal", "-shm"):
            sidecar = self._path.with_name(self._path.name + suffix)
            if sidecar.exists():
                total += sidecar.stat().st_size
        return total

    # ------------------------------------------------------------------ conexão
    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Abre conexão configurada; faz commit no sucesso e rollback no erro."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute("PRAGMA synchronous=NORMAL")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    # ------------------------------------------------------------------ migrações
    def migrate(self) -> MigrationResult:
        """Aplica migrações pendentes em ordem lexicografica."""
        applied: list[str] = []
        with self.connect() as connection:
            connection.execute(SCHEMA_TABLE_SQL)
            done = {
                row["version"] for row in connection.execute("SELECT version FROM schema_migration")
            }
            for version, sql in self._pending_migrations(done):
                connection.executescript(sql)
                connection.execute(
                    "INSERT INTO schema_migration (version, applied_at) "
                    "VALUES (?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))",
                    (version,),
                )
                applied.append(version)
        return MigrationResult(applied=tuple(applied))

    def schema_version(self) -> str | None:
        if not self.exists:
            return None
        with self.connect() as connection:
            try:
                row = connection.execute(
                    "SELECT version FROM schema_migration ORDER BY version DESC LIMIT 1"
                ).fetchone()
            except sqlite3.OperationalError:
                return None
        return str(row["version"]) if row else None

    def integrity_check(self) -> bool:
        if not self.exists:
            return True
        with self.connect() as connection:
            row = connection.execute("PRAGMA integrity_check").fetchone()
        return bool(row) and row[0] == "ok"

    def _pending_migrations(self, done: set[str]) -> list[tuple[str, str]]:
        if not self._migrations_dir.is_dir():
            return []
        pending: list[tuple[str, str]] = []
        for file in sorted(self._migrations_dir.glob("*.sql")):
            version = file.stem
            if version in done:
                continue
            pending.append((version, file.read_text(encoding="utf-8")))
        return pending
