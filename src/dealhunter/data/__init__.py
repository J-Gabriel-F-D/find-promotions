"""Recursos empacotados com a aplicação (migrações, prompts, manifesto de fontes)."""

from __future__ import annotations

from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent
MIGRATIONS_DIR = DATA_DIR / "migrations"
PROMPTS_DIR = DATA_DIR / "prompts"

__all__ = ["DATA_DIR", "MIGRATIONS_DIR", "PROMPTS_DIR"]
