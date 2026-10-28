"""Conversao de valores digitados no terminal para tipos de dominio."""

from __future__ import annotations

import re

import typer

from dealhunter.domain.value_objects.money import Money


def parse_money_option(raw: str | None, *, option: str) -> int | None:
    if raw is None or not raw.strip():
        return None
    try:
        return Money.parse(raw).cents
    except ValueError as exc:
        raise typer.BadParameter(f"valor invalido para {option}: {raw!r}") from exc


def parse_capacity_option(raw: str | None, *, option: str) -> int | None:
    if raw is None or not raw.strip():
        return None
    match = re.search(r"(\d+)", raw)
    if not match:
        raise typer.BadParameter(f"valor invalido para {option}: {raw!r}")
    value = int(match.group(1))
    if value <= 0:
        raise typer.BadParameter(f"valor invalido para {option}: {raw!r}")
    return value


def parse_percent_option(raw: str | None, *, option: str) -> float | None:
    if raw is None or not raw.strip():
        return None
    try:
        value = float(raw.replace("%", "").replace(",", ".").strip())
    except ValueError as exc:
        raise typer.BadParameter(f"percentual invalido para {option}: {raw!r}") from exc
    if not 0 < value <= 100:
        raise typer.BadParameter(f"percentual fora de 0-100 para {option}: {raw!r}")
    return value
