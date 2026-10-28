"""Persistencia local (SQLite)."""

from __future__ import annotations

from dealhunter.adapters.storage.database import Database, MigrationResult

__all__ = ["Database", "MigrationResult"]
